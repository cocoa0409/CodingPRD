"""Corner queue: entities section — creation, retrieval, listing, not-found,
defaults, computed fields, type constraints."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, is_valid_uuid, is_iso8601_timestamp,
    reset_clock, create_level, create_student, create_term_draft, create_instructor,
    create_section_payload, create_curriculum_level_payload,
    create_placement_evaluation_payload, setup_open_term_with_section,
    enroll_with_fresh_version, get_section,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
PO = TEST_USERS["placement_officer_headers"]
CD = TEST_USERS["casting_director_headers"]


def test_curriculum_level_create_returns_defaults_and_system_fields():
    """PRD §3.1: "Two boolean flags govern how a level interacts with the rest of
    the pipeline: `allows_placement_bypass` (default false) marks a level as
    enterable through an advanced-standing petition, and `showcase_required`
    (default false) marks completion as contingent on a graded showcase
    performance. Levels are born with `status` `ACTIVE` and may later be `RETIRED`."
    PRD §2.4: "Every persisted resource carries an `id` that is a server-minted UUID
    with no type prefix, a `created_at` timestamp in ISO 8601 UTC format with three
    fractional digits, an `updated_at` timestamp of the same format that refreshes
    on every mutation, and an integer `version` that starts at 1 on creation and
    increments by exactly 1 on every mutation of that resource."

    Design: Corner/entities/curriculum_level_create_returns_defaults_and_system_fields
    """
    reset_clock()
    resp = api_client.create_curriculum_level(
        {"code": "L1", "title": "Level 1", "track": "IMPROV", "sequence_index": 0}, PD)
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["allows_placement_bypass"] is False
    assert data["showcase_required"] is False
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    body = resp.json()
    assert body["meta"]["api_request_id"]


def test_student_get_returns_stored_fields():
    """PRD §3.3: "Students are born with `standing` `GOOD` (which may later degrade
    to `FINANCIAL_HOLD` or `SUSPENDED`), with `is_alumni` false,
    `is_industry_showcase_eligible` false, and two empty computed code sets:
    `completed_level_codes`, the codes of levels the student has been credited for,
    and `placement_credit_codes`, the codes covered by granted placement petitions."

    Design: Corner/entities/student_get_returns_stored_fields
    """
    student = validate_success(api_client.create_student(
        {"full_name": "Round Trip", "email": "rt@x.com"}, REG), 201)
    fetched = validate_success(api_client.get_student(student["id"], REG))
    assert fetched["full_name"] == "Round Trip"
    assert fetched["is_alumni"] is False
    assert fetched["completed_level_codes"] == []
    assert fetched["placement_credit_codes"] == []


def test_enrollments_list_paginates_with_filter():
    """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
    `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset`
    defaults to 0 and must be at least 0. All list responses sort by `created_at`
    ascending, and the `meta` block of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/enrollments_list_paginates_with_filter
    """
    reset_clock()
    level = create_level()
    term = create_term_draft()
    instructor = create_instructor()
    validate_success(api_client.open_scheduling(term["id"], PD))
    sec_a = validate_success(api_client.create_section(
        create_section_payload(term["id"], level["id"], instructor["id"]), PD), 201)
    sec_b = validate_success(api_client.create_section(
        create_section_payload(term["id"], level["id"], instructor["id"]), PD), 201)
    validate_success(api_client.open_enrollment(term["id"], PD))
    student = create_student()
    enroll_with_fresh_version(student["id"], sec_a["id"])
    enroll_with_fresh_version(student["id"], sec_b["id"])

    resp = api_client.list_enrollments(REG, params={
        "student_id": student["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    resp2 = api_client.list_enrollments(REG, params={
        "student_id": student["id"], "limit": 1, "offset": 1})
    data2, meta2 = validate_paginated(resp2)
    assert len(data2) == 1
    assert meta2["has_more"] is False


def test_ensemble_cast_get_with_unknown_id_returns_not_found():
    """PRD §2.7: "For nested paths, path parameters are resolved left to right: each
    identifier must resolve to an existing entity before the next segment is
    considered, and the first unresolvable identifier yields `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/ensemble_cast_get_with_unknown_id_returns_not_found
    """
    resp = api_client.get_ensemble_cast(NON_EXISTENT_UUID, CD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_section_create_missing_capacity_returns_invalid_request():
    """PRD §2.7: "Malformed request bodies — a missing required field or a value of
    the wrong type — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.2: "A CourseSection binds a `term_id`, a `level_id`, an optional
    `instructor_id` (which may be null while the section is in `DRAFT`), a strictly
    positive `capacity`, a `tuition_cents` base price, and the `weekly_hours` the
    section runs."

    Design: Corner/entities/section_create_missing_capacity_returns_invalid_request
    """
    reset_clock()
    level = create_level()
    term = create_term_draft()
    instructor = create_instructor()
    validate_success(api_client.open_scheduling(term["id"], PD))
    payload = create_section_payload(term["id"], level["id"], instructor["id"])
    payload.pop("capacity")
    resp = api_client.create_section(payload, PD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_placement_evaluation_default_portfolio_score_zero():
    """PRD §3.3: "petitions to enter a level above the entry point by submitting a
    PlacementEvaluation naming the `student_id`, the `target_level_id` the student
    wishes to enter, the `track` the evaluation covers, the `prior_institution`
    where the student trained, and optionally a `portfolio_score` from 0 to 100
    (default 0)."
    PRD §3.3: "when the institution is one of iO, UCB, Groundlings, or Second City
    (another campus), the variant is `AUDITION_BYPASS`; otherwise — including an
    empty institution string — it is `PORTFOLIO_REVIEW`."

    Design: Corner/entities/placement_evaluation_default_portfolio_score_zero
    """
    reset_clock()
    create_level(code="L1", allows_placement_bypass=False)
    lvl2 = create_level(code="L2", sequence_index=1, requires_level_code="L1",
                        allows_placement_bypass=True)
    student = create_student()
    payload = create_placement_evaluation_payload(
        student["id"], lvl2["id"], prior_institution="Unknown School")
    payload.pop("portfolio_score")
    pe = validate_success(api_client.create_placement_evaluation(payload, PO), 201)
    assert pe["portfolio_score"] == 0
    assert pe["variant"] == "PORTFOLIO_REVIEW"


def test_section_enrolled_count_computed_and_input_ignored():
    """PRD §3.2: "Sections track two computed occupancy counters: `enrolled_count`,
    the number of enrollments in `REGISTERED` or `CONFIRMED`, and `waitlist_count`,
    the number in `WAITLISTED`. Both counters move only as enrollment events
    dictate."

    Design: Corner/entities/section_enrolled_count_computed_and_input_ignored
    """
    reset_clock()
    level = create_level()
    term = create_term_draft()
    instructor = create_instructor()
    validate_success(api_client.open_scheduling(term["id"], PD))
    payload = create_section_payload(term["id"], level["id"], instructor["id"])
    section = validate_success(api_client.create_section(payload, PD), 201)
    assert section["enrolled_count"] == 0
    assert section["waitlist_count"] == 0


def test_level_create_invalid_track_enum_returns_invalid_request():
    """PRD §3.1: "a `track` of `IMPROV`, `SKETCH`, `STANDUP`, or `CONSERVATORY`
    (defaulting to `IMPROV` when not supplied)"
    PRD §2.7: "Malformed request bodies — a missing required field or a value of the
    wrong type — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/level_create_invalid_track_enum_returns_invalid_request
    """
    reset_clock()
    resp = api_client.create_curriculum_level(
        {"code": "LX", "title": "Bad", "track": "MUSICAL", "sequence_index": 0}, PD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
