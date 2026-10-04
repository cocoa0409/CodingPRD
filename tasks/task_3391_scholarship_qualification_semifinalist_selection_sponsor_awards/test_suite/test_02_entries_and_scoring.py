"""Schools, students, entries, and scoring — PRD §2.2-2.4, §3.3, §3.4."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    close_entries,
    create_cycle,
    create_entry,
    create_entry_payload,
    create_school,
    create_score_payload,
    create_student,
    create_student_payload,
    get_entry,
    is_iso8601_timestamp,
    is_valid_uuid,
    list_entries,
    list_students,
    make_student_headers,
    open_entries,
    score_entry,
    setup_entry_closed,
    setup_entry_open,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]


def test_create_student_missing_required_field_rejected(api):
    """PRD §2.8: "Field-shape validation last — missing required fields, invalid
    enum members, out-of-range numbers ... all `ERR_INVALID_REQUEST` (HTTP
    400)".
    
    Design: Corner/entities/create_student_missing_required_field_rejected
    """
    school = create_school(name="ZZ High", school_code="ZZ-1", state_code="ZZ")
    payload = create_student_payload(school["id"], full_name="No Citizenship")
    del payload["citizenship_status"]
    resp = api.create_student(payload, PA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert list_students(school_id=school["id"]) == []


def test_entry_computed_selection_index_input_ignored(api):
    """PRD §3.4: "Any client-supplied `selection_index` value is ignored — the
    server always recomputes", the index being "the sum of the three section
    scores multiplied by the section weight 2".
    
    Design: Corner/entities/entry_computed_selection_index_input_ignored
    """
    ctx = setup_entry_closed(score=False)
    payload = create_score_payload(
        reading_score=37, writing_score=37, math_score=38
    )
    payload["selection_index"] = 1  # client-injected; must be ignored
    scored = validate_success(api.score_entry(ctx["entry"]["id"], payload, PA))
    assert scored["selection_index"] == 224  # (37 + 37 + 38) * 2
    assert scored["status"] == "SCORED"


def test_entry_system_fields_ignored_input(api):
    """PRD §3.3: "A new entry starts in `SUBMITTED`". PRD §2.4: "Every persisted
    resource carries a server-minted `id`: a UUID with no type prefix ... and
    an integer `version` that starts at 1 on creation".
    
    Design: Corner/entities/entry_system_fields_ignored_input
    """
    cycle = create_cycle(name="CYC-C4")
    open_entries(cycle["id"])
    school = create_school(name="ZZ High", school_code="ZZ-1", state_code="ZZ")
    student = create_student(school["id"], full_name="F One")
    payload = create_entry_payload(student["id"], cycle["id"])
    payload["status"] = "SCORED"  # system field; must not be honored
    payload["version"] = 99
    entry = validate_success(
        api.create_entry(payload, make_student_headers(student["id"])), 201
    )
    assert entry["status"] == "SUBMITTED"
    assert entry["version"] == 1
    assert is_valid_uuid(entry["id"])
    assert is_iso8601_timestamp(entry["created_at"])
    assert is_iso8601_timestamp(entry["updated_at"])


def test_get_entry_not_found_returns_404(api):
    """PRD §2.9: "the first identifier that fails to resolve produces
    `ERR_NOT_FOUND` (HTTP 404) before any state or business check runs".
    
    Design: Corner/entities/get_entry_not_found_returns_404
    """
    create_cycle(name="CYC-C5")
    resp = api.get_entry(NON_EXISTENT_UUID, PA)
    error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert isinstance(error.get("message"), str) and error["message"]


def test_entries_list_pagination_envelope(api):
    """PRD §2.3: "List endpoints accept two optional query parameters: `limit`
    (default 10, minimum 1, maximum 100) and `offset` (default 0). List
    responses carry the pagination fields `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object", and "list results are sorted by
    `created_at` in ascending order".
    
    Design: Corner/entities/entries_list_pagination_envelope
    """
    ctx = setup_entry_open(student_specs=[{"full_name": "F One"}, {"full_name": "F Two"}])
    cycle_id = ctx["cycle"]["id"]

    data1, meta1 = validate_paginated(
        api.list_entries(PA, params={"cycle_id": cycle_id, "limit": 1, "offset": 0})
    )
    data2, meta2 = validate_paginated(
        api.list_entries(PA, params={"cycle_id": cycle_id, "limit": 1, "offset": 1})
    )
    assert len(data1) == 1 and meta1["total_count"] == 2 and meta1["has_more"] is True
    assert meta1["limit"] == 1 and meta1["offset"] == 0
    assert len(data2) == 1 and meta2["total_count"] == 2 and meta2["has_more"] is False
    assert meta2["offset"] == 1
    ids = {data1[0]["id"], data2[0]["id"]}
    assert ids == {e["id"] for e in ctx["entries"]}, "pages must be disjoint and exhaustive"
    assert data1[0]["id"] == ctx["entries"][0]["id"], "created_at ASC: first-created first"


def test_school_common_fields_false_has_no_version(api):
    """PRD §2.4: "The single exception to the full common-field set is `School`,
    which carries only `id` and `created_at` — both `updated_at` and `version`
    are absent from schools."
    
    Design: Corner/entities/school_common_fields_false_has_no_version
    """
    school = validate_success(
        api.create_school(
            {"name": "Immutable High", "school_code": "ZZ-9", "state_code": "ZZ"}, PA
        ),
        201,
    )
    assert is_valid_uuid(school["id"])
    assert is_iso8601_timestamp(school["created_at"])
    assert "version" not in school
    assert "updated_at" not in school


def test_rescore_scored_entry_rejected(api):
    """PRD §3.4: a ProgramAdmin records section scores "on an entry that is still
    `SUBMITTED`; scoring an entry in any other status is `ERR_INVALID_STATE`".
    
    Design: Corner/state_machines/rescore_scored_entry_rejected
    """
    ctx = setup_entry_closed()  # entry already SCORED with selection_index 224
    resp = api.score_entry(
        ctx["entry"]["id"],
        create_score_payload(reading_score=20, writing_score=20, math_score=20),
        PA,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    entry = get_entry(ctx["entry"]["id"])
    assert entry["selection_index"] == 224
    assert entry["status"] == "SCORED"


def test_section_score_bounds_enforced(api):
    """PRD §3.4: the section scores are "each an integer from 8 to 38 inclusive",
    and PRD §2.8: "out-of-range numbers (section scores 8–38, GPA 0.0–4.0,
    confirming index 48–228, monetary amounts greater than 0), and unordered
    dates (start strictly before end): all `ERR_INVALID_REQUEST` (HTTP 400)".
    
    Design: Corner/calculations/section_score_bounds_enforced
    """
    ctx = setup_entry_closed(score=False)
    resp = api.score_entry(
        ctx["entry"]["id"],
        create_score_payload(reading_score=37, writing_score=37, math_score=39),
        PA,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert get_entry(ctx["entry"]["id"])["status"] == "SUBMITTED"
    scored = score_entry(ctx["entry"]["id"], 37, 37, 38)
    assert scored["selection_index"] == 224
    assert scored["status"] == "SCORED"


def test_score_response_immediately_consistent(api):
    """PRD §3.4: "The server then computes the entry's `selection_index` as the
    sum of the three section scores multiplied by the section weight 2 ... the
    entry moves `SUBMITTED` → `SCORED`".
    
    Design: Corner/consistency_model/score_response_immediately_consistent
    """
    ctx = setup_entry_closed(score=False)
    scored = validate_success(
        api.score_entry(
            ctx["entry"]["id"],
            create_score_payload(reading_score=37, writing_score=37, math_score=38),
            PA,
        )
    )
    assert scored["selection_index"] == 224
    assert scored["status"] == "SCORED"
    reread = get_entry(ctx["entry"]["id"])
    assert reread["selection_index"] == scored["selection_index"]
    assert reread["status"] == scored["status"]


def test_entry_ineligible_requirements_rejected(api):
    """PRD §3.3: "Four entry requirements apply, each failed requirement a
    rejection with `ERR_ENTRY_INELIGIBLE` (HTTP 422): the student's
    `citizenship_status` must not be `OTHER` ... and the examination must have
    been taken in `THIRD_YEAR`."
    
    Design: Corner/validations/entry_ineligible_requirements_rejected
    """
    cycle = create_cycle(name="CYC-V2")
    open_entries(cycle["id"])
    school = create_school(name="ZZ High", school_code="ZZ-1", state_code="ZZ")
    stu_a = create_student(school["id"], full_name="S A", citizenship_status="OTHER")
    stu_b = create_student(school["id"], full_name="S B")

    resp_a = api.create_entry(
        create_entry_payload(stu_a["id"], cycle["id"]),
        make_student_headers(stu_a["id"]),
    )
    validate_error(resp_a, ApiErrorId.ERR_ENTRY_INELIGIBLE)
    resp_b = api.create_entry(
        create_entry_payload(stu_b["id"], cycle["id"], exam_year_of_hs="SECOND_YEAR"),
        make_student_headers(stu_b["id"]),
    )
    validate_error(resp_b, ApiErrorId.ERR_ENTRY_INELIGIBLE)
    assert list_entries(cycle_id=cycle["id"]) == []


def test_duplicate_entry_rejected_in_open_posture(api):
    """PRD §3.3: "One entry per student per cycle is a hard rule — a second entry
    for the same student in the same cycle is `ERR_DUPLICATE_ENTRY` (HTTP
    409)."
    
    Design: Corner/validations/duplicate_entry_rejected_in_open_posture
    """
    ctx = setup_entry_open()  # one entry already exists for the student
    cycle_id, student_id = ctx["cycle"]["id"], ctx["student"]["id"]
    resp = api.create_entry(
        create_entry_payload(student_id, cycle_id), make_student_headers(student_id)
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENTRY)
    assert len(list_entries(student_id=student_id, cycle_id=cycle_id)) == 1


def test_scoring_rejected_while_cycle_entry_open(api):
    """PRD §3.4: "Scoring begins only after the entry window closes: the entry's
    cycle must be in `ENTRY_CLOSED` posture, or the attempt is
    `ERR_CYCLE_NOT_CLOSED_FOR_SCORING` (HTTP 409)."
    
    Design: Difficulty/cross_entity_state_dependency/scoring_gated_by_cycle_posture
    """
    ctx = setup_entry_open()  # cycle ENTRY_OPEN, entry SUBMITTED
    resp = api.score_entry(
        ctx["entry"]["id"],
        create_score_payload(reading_score=37, writing_score=37, math_score=38),
        PA,
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_CLOSED_FOR_SCORING)
    entry = get_entry(ctx["entry"]["id"])
    assert entry["status"] == "SUBMITTED"
    assert entry["selection_index"] is None


def test_scoring_accepted_once_cycle_entry_closed(api):
    """PRD §3.4: "Scoring begins only after the entry window closes: the entry's
    cycle must be in `ENTRY_CLOSED` posture, or the attempt is
    `ERR_CYCLE_NOT_CLOSED_FOR_SCORING` (HTTP 409)."
    
    Design: Difficulty/cross_entity_state_dependency/scoring_gated_by_cycle_posture
    """
    ctx = setup_entry_open()
    close_entries(ctx["cycle"]["id"])
    scored = score_entry(ctx["entry"]["id"], 37, 37, 38)
    assert scored["status"] == "SCORED"
    assert scored["selection_index"] == 224
    assert is_iso8601_timestamp(scored["scored_at"])


def test_closed_cycle_entry_create_state_gate_beats_duplicate(api):
    """PRD §2.8: checks run in "a fixed priority order so that the surfaced error
    is deterministic": "6. State gates — the cycle posture gates
    `ERR_CYCLE_NOT_ACCEPTING_ENTRIES` ... " come before "7. Business
    constraints — duplicates and uniqueness (`ERR_DUPLICATE_ENTRY` ... )".
    
    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_duplicate_entry
    """
    ctx = setup_entry_closed(score=False)  # entry exists; cycle now ENTRY_CLOSED
    cycle_id, student_id = ctx["cycle"]["id"], ctx["student"]["id"]
    resp = api.create_entry(
        create_entry_payload(student_id, cycle_id), make_student_headers(student_id)
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_ACCEPTING_ENTRIES)


def test_closed_cycle_duplicate_entry_persists_nothing(api):
    """PRD §2.8: state gates (priority 6, ERR_CYCLE_NOT_ACCEPTING_ENTRIES) are
    evaluated before business constraints (priority 7, ERR_DUPLICATE_ENTRY),
    so the doubly-invalid request surfaces the state error and writes nothing.
    PRD §3.3: "Entries may be created only while the cycle is `ENTRY_OPEN`".
    
    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_constraint_on_duplicate_entry
    """
    ctx = setup_entry_closed(score=False)
    cycle_id, student_id = ctx["cycle"]["id"], ctx["student"]["id"]
    resp = api.create_entry(
        create_entry_payload(student_id, cycle_id), make_student_headers(student_id)
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_ACCEPTING_ENTRIES)
    assert len(list_entries(student_id=student_id, cycle_id=cycle_id)) == 1
