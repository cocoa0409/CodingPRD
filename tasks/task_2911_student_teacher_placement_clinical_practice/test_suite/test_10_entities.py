"""The persisted shape of each resource, read back through the envelope.

These tests are about what the store actually holds: which members a created row
echoes, which values the server mints for itself, which declared defaults apply
when an optional field is omitted, and which of the ladder's early rungs a
malformed or dangling reference lands on.  Nothing here exercises a workflow;
every assertion is about a row and the envelope that carries it.
"""
from test_helpers import (
    CREDENTIAL_ANALYST,
    NON_EXISTENT_UUID,
    PLACEMENT_COORDINATOR,
    PROGRAM_ADMIN,
    SUPERVISION_LEAD,
    ERR_CANDIDATE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PLACEMENT_NOT_FOUND,
    add_teacher,
    assert_envelope,
    assert_instant_equals,
    assert_page_meta,
    factories as f,
    is_valid_uuid,
    open_request,
    read_candidate,
    route,
    setup_bench,
    setup_ready_candidate,
    validate_error,
    validate_page,
    validate_success,
)

# The district of the design's own worked example.
RIDGEVIEW = {
    "name": "Ridgeview ISD",
    "district_code": "D-RIDGE",
    "state_code": "TX",
    "requires_district_fingerprint": True,
    "travel_reimbursement_enabled": True,
}
ANA_DIAZ = {
    "candidate_code": "C-1001",
    "full_name": "Ana Diaz",
    "program_track": "SECONDARY",
    "home_grid_x": 2,
    "home_grid_y": 4,
}
CLOCK_AT_START = "2026-08-01T00:00:00Z"
# Values the server must mint for itself, offered in the body to be ignored.
FORGED_SYSTEM_FIELDS = {
    "id": NON_EXISTENT_UUID,
    "created_at": "2000-01-01T00:00:00Z",
    "updated_at": "2000-01-01T00:00:00Z",
    "version": 99,
}
FORGED_LEDGER = {
    "placement_cap": 3,
    "seats_reserved": 7,
    "seats_committed": 7,
    "stipend_committed_cents": 999999,
    "capacity_posture": "CAP_REACHED",
    "status": "ACTIVE",
}


def test_create_district_returns_the_created_row_with_declared_fields(api):
    """201, the object envelope, and every stored field echoed back.

    PRD §3.3: "a `ProgramAdmin` registers the partner district itself: a `name`
    of 1 to 120 characters, a `district_code` of 1 to 32 characters that must be
    unique across all districts ... and a `state_code` of exactly two uppercase
    letters".  PRD §2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources."  PRD §2.4: "`version` is an
    integer that starts at `1` when the row is created".

    Design: Corner/entities/create_district_returns_the_created_row_with_declared_fields
    """
    response = api.create_district(f.district_payload(**RIDGEVIEW), PROGRAM_ADMIN)

    body = assert_envelope(response)
    district = validate_success(response, 201)
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)

    assert district["name"] == "Ridgeview ISD"
    assert district["district_code"] == "D-RIDGE"
    assert district["state_code"] == "TX"
    assert district["requires_district_fingerprint"] is True
    assert district["travel_reimbursement_enabled"] is True
    assert isinstance(district["id"], str) and district["id"]
    assert district["version"] == 1


def test_get_candidate_returns_the_stored_row_with_initial_derived_fields(api):
    """The input fields survive the round trip and every gate starts closed.

    PRD §3.1: "A newly admitted candidate begins with `readiness_status` at
    `NOT_READY`, `licensure_status` at `PENDING`, `report_status` at
    `UNREPORTED`, `readiness_score` at 0 and `readiness_variant_used` at null.
    Every audit field of the candidate — `recommended_by_user_id`,
    `recommended_at`, `denial_reason`, `reported_by_user_id`, `reported_at`,
    `reporting_cycle` and `state_report_deadline` — is null at admission."

    Design: Corner/entities/get_candidate_returns_the_stored_row_with_initial_derived_fields
    """
    created = validate_success(
        api.create_candidate(f.candidate_payload(**ANA_DIAZ), PROGRAM_ADMIN), 201)
    # PRD §3.1 pins readiness_variant_used at null for the *newly admitted*
    # candidate; PRD is silent on whether the STRICT re-derivation a single
    # candidate read performs also records the variant it ran under, so the
    # admission response is the only place the null is uniquely derivable.
    assert created["readiness_variant_used"] is None

    candidate = read_candidate(api, created["id"])

    assert candidate["candidate_code"] == "C-1001"
    assert candidate["full_name"] == "Ana Diaz"
    assert candidate["program_track"] == "SECONDARY"
    assert candidate["home_grid_x"] == 2
    assert candidate["home_grid_y"] == 4
    assert candidate["readiness_score"] == 0
    assert candidate["readiness_status"] == "NOT_READY"
    assert candidate["licensure_status"] == "PENDING"
    assert candidate["report_status"] == "UNREPORTED"
    assert candidate["state_report_deadline"] is None


def test_list_readiness_items_filtered_by_candidate_is_paginated(api):
    """Three of this candidate's items, sliced two and one, and nobody else's.

    PRD §2.3: "the pagination slots of the `meta` object are populated as `page`
    (the page actually served), `page_size` (the page size actually applied),
    `total_count` (the number of rows matching the filters before slicing) and
    `has_more` (true when rows remain beyond the served page)."  PRD §3.1:
    "Items can be browsed filtered by `candidate_id`, `item_type` and `status`."

    Design: Corner/entities/list_readiness_items_filtered_by_candidate_is_paginated
    """
    mine = validate_success(
        api.create_candidate(f.candidate_payload(), PROGRAM_ADMIN), 201)
    other = validate_success(
        api.create_candidate(f.candidate_payload(), PROGRAM_ADMIN), 201)
    for payload in (f.exam_item_payload(mine["id"]),
                    f.clearance_item_payload(mine["id"]),
                    f.coursework_item_payload(mine["id"]),
                    f.exam_item_payload(other["id"])):
        validate_success(api.create_readiness_item(payload, CREDENTIAL_ANALYST), 201)

    first_page, first_meta = validate_page(api.list_readiness_items(
        CREDENTIAL_ANALYST,
        params={"candidate_id": mine["id"], "page": 1, "page_size": 2}))
    second_page, second_meta = validate_page(api.list_readiness_items(
        CREDENTIAL_ANALYST,
        params={"candidate_id": mine["id"], "page": 2, "page_size": 2}))

    assert len(first_page) == 2
    assert_page_meta(first_meta, page=1, page_size=2, total_count=3, has_more=True)
    assert len(second_page) == 1
    assert_page_meta(second_meta, page=2, page_size=2, total_count=3, has_more=False)
    for row in first_page + second_page:
        assert row["candidate_id"] == mine["id"]
        assert row["status"] == "PENDING_VERIFICATION"


def test_get_placement_with_an_unknown_id_returns_placement_not_found(api):
    """The path id decides the code, and it is the placement's own 404.

    PRD §2.6: "Every id embedded in the URL path exists, validated left to right;
    the first missing resource decides the error, which is that entity's own 404
    code — ... `ERR_PLACEMENT_NOT_FOUND` ... (all 404)."  PRD §2.2: "The
    `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/get_placement_with_an_unknown_id_returns_placement_not_found
    """
    response = api.get_placement(NON_EXISTENT_UUID, PLACEMENT_COORDINATOR)

    error = validate_error(response, ERR_PLACEMENT_NOT_FOUND, 404)

    assert response.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"]


def test_create_placement_request_without_term_start_date_is_invalid(api):
    """A missing required field is refused at rung 6 and persists nothing.

    PRD §2.6: "The request body is well shaped: every required field is present
    ... otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint that has
    a request body."

    Design: Corner/entities/create_placement_request_without_term_start_date_returns_invalid_request
    """
    scenario = setup_bench(api)
    setup_ready_candidate(api, scenario=scenario)
    payload = f.placement_request_payload(
        scenario.candidate_id, preferred_district_id=scenario.district_id)
    del payload["term_start_date"]

    validate_error(api.create_placement_request(payload, PLACEMENT_COORDINATOR),
                   ERR_INVALID_REQUEST, 400)

    _rows, meta = validate_page(api.list_placement_requests(
        PLACEMENT_COORDINATOR, params={"candidate_id": scenario.candidate_id}))
    assert meta["total_count"] == 0, "the refused request left no row behind"


def test_create_cooperating_teacher_applies_the_declared_defaults(api):
    """Omitted optionals take their declared values, on the teacher and the district.

    PRD §3.4: "`consecutive_terms_hosted`, an integer from 0 through 20
    defaulting to 0 ... `max_concurrent_candidates`, from 1 through 3 and
    defaulting to 1 ... Every new teacher starts at `PENDING_TRAINING` with
    `active_placement_count` at 0, and with `training_completed_on`,
    `training_expires_on` and `disqualification_reason` null."  PRD §3.3:
    "`requires_district_fingerprint`, which defaults to false ...
    `travel_reimbursement_enabled`, which defaults to true".

    Design: Corner/entities/create_cooperating_teacher_applies_the_declared_defaults
    """
    district_payload = f.district_payload()
    del district_payload["requires_district_fingerprint"]
    del district_payload["travel_reimbursement_enabled"]
    district = validate_success(
        api.create_district(district_payload, PROGRAM_ADMIN), 201)
    teacher_payload = f.teacher_payload(district["id"])
    del teacher_payload["consecutive_terms_hosted"]
    del teacher_payload["max_concurrent_candidates"]

    teacher = validate_success(
        api.create_teacher(teacher_payload, SUPERVISION_LEAD), 201)

    assert teacher["consecutive_terms_hosted"] == 0
    assert teacher["max_concurrent_candidates"] == 1
    assert teacher["qualification_status"] == "PENDING_TRAINING"
    assert teacher["training_completed_on"] is None
    assert teacher["training_expires_on"] is None
    assert teacher["disqualification_reason"] is None
    assert teacher["active_placement_count"] == 0

    stored = validate_success(api.get_district(district["id"], PROGRAM_ADMIN))
    assert stored["requires_district_fingerprint"] is False
    assert stored["travel_reimbursement_enabled"] is True


def test_create_agreement_seat_counters_are_computed_not_accepted(api):
    """A fresh agreement's ledger is zero however the body was decorated.

    PRD §3.3: "A fresh agreement is `DRAFT`, with `seats_reserved`,
    `seats_committed` and `stipend_committed_cents` all at 0, `capacity_posture`
    at `OPEN` and `suspension_reason` null."  PRD §2.9: "Three derived totals in
    this system are **conserved quantities** — they are never incremented by
    hand, they are re-derived from the underlying rows every time anything that
    feeds them changes".

    Design: Corner/entities/create_agreement_seat_counters_are_computed_input_ignored
    """
    district = validate_success(
        api.create_district(f.district_payload(), PROGRAM_ADMIN), 201)

    agreement = validate_success(api.create_agreement(
        f.agreement_payload(district["id"], **FORGED_LEDGER), PROGRAM_ADMIN), 201)

    assert agreement["seats_reserved"] == 0
    assert agreement["seats_committed"] == 0
    assert agreement["stipend_committed_cents"] == 0
    assert agreement["capacity_posture"] == "OPEN"
    assert agreement["status"] == "DRAFT", "the supplied status was ignored too"
    assert agreement["suspension_reason"] is None
    assert agreement["placement_cap"] == 3
    assert agreement["stipend_rate_cents_per_week"] == 12345


def test_create_district_system_fields_are_minted_by_the_server(api):
    """The id, the audit instants and the version come from the server and the clock.

    PRD §2.4: "`id` is a server-minted UUID with no type prefix; clients never
    supply it. `created_at` is the ISO 8601 UTC instant of creation ...
    `updated_at` ... equals `created_at` on a freshly created row. `version` is
    an integer that starts at `1` when the row is created".  PRD §2.5: "Before
    any administrator has set it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`".

    Design: Corner/entities/create_district_system_fields_are_generated_input_ignored
    """
    payload = f.district_payload(**FORGED_SYSTEM_FIELDS)
    del payload["requires_district_fingerprint"]
    del payload["travel_reimbursement_enabled"]

    district = validate_success(api.create_district(payload, PROGRAM_ADMIN), 201)

    assert district["id"] != NON_EXISTENT_UUID
    assert is_valid_uuid(district["id"])
    assert_instant_equals(district["created_at"], CLOCK_AT_START, "created_at")
    assert_instant_equals(district["updated_at"], CLOCK_AT_START, "updated_at")
    assert district["version"] == 1, "the version starts at 1, not at the supplied 99"


def test_create_candidate_with_an_undeclared_program_track_is_invalid(api):
    """A non-member enum and an out-of-range coordinate both stop at rung 6.

    PRD §2.6: "every enum value is a declared member, every integer is inside its
    declared range ... otherwise `ERR_INVALID_REQUEST` (400)."  PRD §2.12: "A
    candidate's `program_track` is one of `ELEMENTARY`, `SECONDARY`,
    `SPECIAL_ED`."  PRD §3.1: "each grid coordinate is an integer from −500
    through 500."

    Design: Corner/entities/create_candidate_with_an_undeclared_program_track_returns_invalid_request
    """
    validate_error(api.create_candidate(
        f.candidate_payload(candidate_code="C-9999", full_name="Ivy Stone",
                            program_track="MIDDLE_GRADES"), PROGRAM_ADMIN),
        ERR_INVALID_REQUEST, 400)

    validate_error(api.create_candidate(
        f.candidate_payload(candidate_code="C-9998", full_name="Ivy Stone",
                            home_grid_x=900), PROGRAM_ADMIN),
        ERR_INVALID_REQUEST, 400)

    _rows, meta = validate_page(api.list_candidates(PROGRAM_ADMIN))
    assert meta["total_count"] == 0, "neither refused admission created a row"


def test_create_readiness_item_for_an_unknown_candidate_is_not_found(api):
    """A dangling body foreign key answers with the referenced entity's own 404.

    PRD §2.6: "Every foreign key supplied in the request body references an
    existing row — `candidate_id`, `district_id`, `placement_id`, `supervisor_id`
    and the rest — reported with that entity's own 404 code. Applies to
    readiness-item creation".  PRD §3.1: "a `candidate_id` that names no
    candidate is refused with `ERR_CANDIDATE_NOT_FOUND`."

    Design: Corner/entities/create_readiness_item_for_an_unknown_candidate_returns_candidate_not_found
    """
    validate_error(api.create_readiness_item(
        f.exam_item_payload(NON_EXISTENT_UUID), CREDENTIAL_ANALYST),
        ERR_CANDIDATE_NOT_FOUND, 404)

    _rows, meta = validate_page(api.list_readiness_items(CREDENTIAL_ANALYST))
    assert meta["total_count"] == 0, "no item was filed against a missing candidate"


def test_list_placements_filtered_by_cooperating_teacher_id_resolves_the_key(api):
    """The matched mentor's list holds the placement; the passed-over mentor's is empty.

    PRD §2.3: "Filter query parameters on a list endpoint are conjunctive:
    supplying two filters narrows the result to rows matching both."  PRD §3.4:
    "The distance surcharge is derived from the Manhattan distance between the
    supervisor's base and the teacher's site".

    Design: Corner/entities/list_placements_filtered_by_cooperating_teacher_id_resolves_the_foreign_key
    """
    scenario = setup_bench(api)
    add_teacher(api, scenario, site_grid_x=10, site_grid_y=11, years_experience=6)
    setup_ready_candidate(api, scenario=scenario)
    scenario.request = open_request(api, scenario.candidate_id,
                                   preferred_district_id=scenario.district_id)
    placement = route(api, scenario.request_id)

    matched, matched_meta = validate_page(api.list_placements(
        PLACEMENT_COORDINATOR,
        params={"cooperating_teacher_id": scenario.teacher_id}))
    passed_over, passed_over_meta = validate_page(api.list_placements(
        PLACEMENT_COORDINATOR,
        params={"cooperating_teacher_id": scenario.second_teacher["id"]}))

    assert matched_meta["total_count"] == 1
    assert matched[0]["id"] == placement["id"]
    assert matched[0]["cooperating_teacher_id"] == scenario.teacher_id
    assert passed_over == []
    assert passed_over_meta["total_count"] == 0
    assert passed_over_meta["has_more"] is False
    assert matched[0]["candidate_id"] == scenario.candidate_id
    assert matched[0]["agreement_id"] == scenario.agreement_id
    assert matched[0]["supervisor_id"] == scenario.supervisor_id
