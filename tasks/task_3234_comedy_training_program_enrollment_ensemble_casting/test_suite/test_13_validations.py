"""Corner queue: validations — cycle rejection, instructor availability,
scholarship revocation guard."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, ApiErrorId,
    create_level, create_student, create_term_draft, create_instructor,
    create_section_payload, reset_clock, setup_open_term_with_section,
    enroll_with_fresh_version, create_scholarship_payload, get_scholarship,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
FO = TEST_USERS["finance_officer_headers"]


def test_curriculum_level_prerequisite_cycle_rejected():
    """PRD §2.8: "Creating or updating a level walks the prerequisite chain from the
    level being written; if the walk ever revisits a node, the write is rejected
    with `ERR_PREREQUISITE_CYCLE` (HTTP 422)."

    Design: Corner/validations/curriculum_level_prerequisite_cycle_rejected
    """
    reset_clock()
    create_level(code="L1")
    create_level(code="L3", sequence_index=2, requires_level_code="L1")
    resp = api_client.create_curriculum_level(
        {"code": "LSELF", "title": "Self Ref", "track": "IMPROV",
         "sequence_index": 9, "requires_level_code": "LSELF"}, PD)
    validate_error(resp, ApiErrorId.ERR_PREREQUISITE_CYCLE, 422)


def test_instructor_overloaded_weekly_hours_rejected():
    """PRD §3.2: "the instructor's total weekly load across their sections plus this
    section's `weekly_hours` must not exceed the instructor's `max_weekly_hours`. A
    violation of either is rejected with `ERR_INSTRUCTOR_UNAVAILABLE` (HTTP 422)."

    Design: Corner/validations/instructor_overloaded_weekly_hours_rejected
    """
    reset_clock()
    level = create_level()
    term = create_term_draft()
    instructor = create_instructor(max_weekly_hours=5)
    validate_success(api_client.open_scheduling(term["id"], PD))
    validate_success(api_client.create_section(
        create_section_payload(term["id"], level["id"], instructor["id"],
                               weekly_hours=3), PD), 201)
    resp = api_client.create_section(
        create_section_payload(term["id"], level["id"], instructor["id"],
                               weekly_hours=3), PD)
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_UNAVAILABLE, 422)


def test_instructor_wrong_track_certification_rejected():
    """PRD §3.2: "the instructor must be certified for the track of the section's
    level, and the instructor's total weekly load across their sections plus this
    section's `weekly_hours` must not exceed the instructor's `max_weekly_hours`. A
    violation of either is rejected with `ERR_INSTRUCTOR_UNAVAILABLE` (HTTP 422)."

    Design: Corner/validations/instructor_wrong_track_certification_rejected
    """
    reset_clock()
    create_level(code="L1")
    sketch_level = create_level(code="SK1", track="SKETCH")
    term = create_term_draft()
    instructor = create_instructor(certified_tracks=["IMPROV"], home_track="IMPROV")
    validate_success(api_client.open_scheduling(term["id"], PD))
    resp = api_client.create_section(
        create_section_payload(term["id"], sketch_level["id"], instructor["id"]), PD)
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_UNAVAILABLE, 422)


def test_scholarship_revoke_with_disbursed_balance_rejected():
    """PRD §3.4: "An award can be revoked (`AWARDED → REVOKED`, terminal) only
    while nothing has been disbursed; attempting to revoke an award whose
    `disbursed_cents` is non-zero fails with `ERR_SCHOLARSHIP_NOT_REVOCABLE`
    (HTTP 409)."

    Design: Corner/validations/scholarship_revoke_with_disbursed_balance_rejected
    """
    ctx = setup_open_term_with_section(capacity=4, tuition_cents=10000)
    student = create_student()
    sch = validate_success(api_client.create_scholarship(
        create_scholarship_payload(student["id"], kind="NEED_BASED",
                                   amount_cents=5000), FO), 201)
    validate_success(api_client.award_scholarship(sch["id"], FO))
    enroll_with_fresh_version(student["id"], ctx["section"]["id"])
    # The invoice issuance disbursed the award
    assert get_scholarship(sch["id"])["status"] == "DISBURSED"
    resp = api_client.revoke_scholarship(sch["id"], FO)
    validate_error(resp, ApiErrorId.ERR_SCHOLARSHIP_NOT_REVOCABLE, 409)
