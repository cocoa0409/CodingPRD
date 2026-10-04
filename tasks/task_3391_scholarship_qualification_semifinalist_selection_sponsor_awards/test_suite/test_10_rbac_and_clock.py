"""Role/ownership enforcement and logical-clock monotonicity — PRD §2.1,
§2.5, §2.8, §3.4, §3.5, §3.8.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    accept_award,
    advance_clock,
    create_application,
    create_college_institution,
    create_cycle,
    create_renewal_decision_payload,
    create_school,
    create_score_payload,
    decide_renewal,
    find_award,
    get_application,
    get_entry,
    make_college_admin_headers,
    make_school_official_headers,
    make_student_headers,
    setup_entry_closed,
    setup_entry_open,
    setup_finalists_selected,
    setup_matching_run,
    setup_renewal_submitted,
    setup_semifinalists_selected,
    validate_error,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]

_RENEWABLE_COLLEGE = {
    "award_amount_cents": 100000,
    "renewable_years_total": 2,
    "terms_per_year": 1,
    "pool_total_cents": 500000,
    "max_awards": 5,
}


def test_unauthenticated_request_beats_not_found(api):
    """PRD §2.1: "A request missing either header, or presenting a role the
    system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)
    before any other check runs — even before path identifiers are resolved."
    
    Design: Corner/validations/unauthenticated_request_beats_not_found
    """
    create_cycle(name="CYC-V1")
    resp = api.get_entry(NON_EXISTENT_UUID, None)  # no X-User-Role / X-User-ID
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_student_cannot_score_entry_forbidden(api):
    """PRD §3.4: "A `ProgramAdmin` records the three preliminary-examination
    section scores"; PRD §2.1: "A request whose role is declared but not
    listed for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP
    403)."
    
    Design: Corner/rbac/student_cannot_score_entry_forbidden
    """
    ctx = setup_entry_closed(score=False)
    resp = api.score_entry(
        ctx["entry"]["id"],
        create_score_payload(reading_score=37, writing_score=37, math_score=38),
        make_student_headers(ctx["student"]["id"]),  # right entity, wrong role
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    entry = get_entry(ctx["entry"]["id"])
    assert entry["status"] == "SUBMITTED"
    assert entry["selection_index"] is None


def test_school_endorsement_wrong_school_rejected(api):
    """PRD §3.5: "A `SchoolOfficial` endorses an application whose student's
    `school_id` equals the official's `X-User-ID` — any other pairing is
    `ERR_ENDORSEMENT_SCHOOL_MISMATCH` (HTTP 403)".
    
    Design: Corner/rbac/school_endorsement_wrong_school_rejected
    """
    ctx = setup_semifinalists_selected()
    other_school = create_school(name="ZZ Other", school_code="ZZ-2", state_code="ZZ")
    app = create_application(ctx["entry"]["id"], ctx["student"]["id"])
    resp = api.endorse_application(
        app["id"], make_school_official_headers(other_school["id"])
    )
    validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_SCHOOL_MISMATCH)
    after = get_application(app["id"])
    assert after["endorsement_status"] == "PENDING"
    assert after["endorsed_by_school_id"] is None


def test_program_admin_cannot_endorse_forbidden(api):
    """PRD §3.5: "Endorsement comes from the student's school. A `SchoolOfficial`
    endorses an application ... "; the endpoint is listed for SchoolOfficial
    only (PRD §4), and "A request whose role is declared but not listed for
    the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)" (PRD
    §2.1).
    
    Design: Corner/rbac/program_admin_cannot_endorse_forbidden
    """
    ctx = setup_semifinalists_selected()
    app = create_application(ctx["entry"]["id"], ctx["student"]["id"])
    resp = api.endorse_application(app["id"], PA)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_application(app["id"])["endorsement_status"] == "PENDING"


def test_college_admin_cannot_decide_renewal_forbidden(api):
    """PRD §3.8: "College-sponsored awards renew yearly behind a segregation of
    duties: the institution reports, the program decides, and neither can
    perform the other's step."
    
    Design: Corner/rbac/college_admin_cannot_decide_renewal_forbidden
    """
    ctx = setup_renewal_submitted(
        student_specs=[{"first_choice_college": True}],
        college_overrides=_RENEWABLE_COLLEGE,
    )
    renewal = ctx["renewal"]
    resp = api.decide_renewal_verification(
        renewal["id"],
        create_renewal_decision_payload("APPROVE"),
        make_college_admin_headers(ctx["college"]["id"]),  # the submitter's role
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    decided = decide_renewal(renewal["id"], "APPROVE")  # ProgramAdmin succeeds
    assert decided["status"] == "APPROVED"


def test_student_cannot_accept_others_award_forbidden(api):
    """PRD §3.8: "Only the recipient may act — `X-User-ID` equal to the award's
    `student_id`, else `ERR_FORBIDDEN_OWNERSHIP`".
    
    Design: Corner/rbac/student_cannot_accept_others_award_forbidden
    """
    ctx = setup_matching_run(
        student_specs=[
            {"scores": (37, 37, 38), "confirming_selection_index": 212},
            {"scores": (37, 37, 37), "confirming_selection_index": 208},
        ],
        cycle_overrides={"national_award_slots": 1},
    )
    f1, f2 = ctx["students"]
    aw1 = find_award(f1["id"], ctx["cycle"]["id"])
    assert aw1["recipient_status"] == "OFFERED"

    resp = api.accept_award(aw1["id"], make_student_headers(f2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    accepted = accept_award(aw1["id"], f1["id"])  # the forbidden try consumed nothing
    assert accepted["recipient_status"] == "ACCEPTED"


def test_clock_regression_rejected(api):
    """PRD §2.5: "The clock is monotonic: setting it to an instant less than or
    equal to the current value is rejected with `ERR_CLOCK_REGRESSION` (HTTP
    422)."
    
    Design: Corner/errors/clock_regression_rejected
    """
    create_cycle(name="CYC-E5")
    advance_clock("2027-01-01T00:00:00Z")
    resp = api.set_clock("2027-01-01T00:00:00Z", PA)  # equal is not an advance
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)
    moved = advance_clock("2027-01-02T00:00:00Z")  # strictly later succeeds
    assert moved["current_utc"] == "2027-01-02T00:00:00Z"
