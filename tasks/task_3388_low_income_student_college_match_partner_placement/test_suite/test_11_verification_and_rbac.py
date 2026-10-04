"""Income verification: the discrepancy boundary, segregation of duties, the
terminal-outcome guard — plus the RBAC deny probes across roles."""
from test_helpers import (
    ApiErrorId,
    CLOCK_IN_RANKING_WINDOW,
    TEST_USERS,
    advance_cycle_to_phase,
    create_application,
    create_college,
    create_community_partner,
    create_counselor,
    create_cycle,
    create_cycle_payload,
    create_income_verification,
    create_referral,
    create_student,
    decide_verification,
    decide_verification_payload,
    expect_error,
    get_application,
    get_current_rankings,
    make_counselor_headers,
    make_partner_staff_headers,
    make_student_headers,
    ranking_entry,
    reset_clock,
    set_clock,
    setup_finalist_application,
    setup_submitted_application,
    submit_application,
    submit_rankings_payload,
    validate_paginated,
)

_ADMIN = TEST_USERS["program_admin_headers"]


def test_discrepancy_exactly_ten_percent_is_verified(api):
    """PRD §3.6: "Otherwise the absolute difference between
    `verified_income_cents` and the reported `household_income_cents` is
    compared against ten percent of the reported figure using exact integer
    cross-multiplication — no floating point anywhere: a difference strictly
    greater than ten percent lands in `DISCREPANCY`, while a difference of
    exactly ten percent or less is `VERIFIED`."
    PRD §3.6: "Whatever the decision, `decided_by_partner_id` is set from the
    decider's `X-User-ID` — it stays null until a decision — and the
    application's `verification_flag` follows the outcome."

    Design: Corner/calculations/discrepancy_exactly_ten_percent_is_verified
    """
    ctx = setup_submitted_application()
    student_b = create_student()
    app_b = create_application(student_b["id"], ctx["cycle"]["id"])
    submit_application(app_b["id"], student_b["id"])
    advance_cycle_to_phase(ctx["cycle"]["id"], "REVIEW")
    counselor = create_counselor()
    partner = create_community_partner()
    iv_exact = create_income_verification(
        ctx["application"]["id"], make_counselor_headers(counselor["id"]),
        verified_income_cents=7150000, verified_assets_cents=0,
        verified_household_size=4,
    )
    iv_over = create_income_verification(
        app_b["id"], make_counselor_headers(counselor["id"]),
        verified_income_cents=7150001, verified_assets_cents=0,
        verified_household_size=4,
    )
    exact = decide_verification(iv_exact["id"], partner["id"], "VERIFY")
    over = decide_verification(iv_over["id"], partner["id"], "VERIFY")
    assert exact["outcome"] == "VERIFIED", (
        "650,000 over 6,500,000 is exactly ten percent — VERIFIED"
    )
    assert over["outcome"] == "DISCREPANCY", (
        "650,001 over 6,500,000 is strictly greater than ten percent"
    )
    assert get_application(ctx["application"]["id"])["verification_flag"] == "VERIFIED"
    assert get_application(app_b["id"])["verification_flag"] == "DISCREPANCY"


def test_referring_partner_cannot_decide_that_applications_verification(api):
    """PRD §3.6: "One conflict-of-interest rule overrides everything else: the
    deciding partner's `X-User-ID` must differ from the record's
    `submitted_by_partner_id`, and it must also differ from the `partner_id`
    of any referral the application cites. The organization that submitted the
    documents and the organization that nominated the student are both barred
    from judging them; a violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/referring_partner_cannot_decide_that_applications_verification
    """
    reset_clock()
    cycle = create_cycle()
    advance_cycle_to_phase(cycle["id"], "RECRUITMENT")
    counselor = create_counselor()
    referring_partner = create_community_partner()
    unrelated_partner = create_community_partner()
    student = create_student()
    referral = create_referral(
        student["id"], cycle["id"],
        make_partner_staff_headers(referring_partner["id"]),
    )
    advance_cycle_to_phase(cycle["id"], "APPLICATION_OPEN")
    application = create_application(
        student["id"], cycle["id"], referral_id=referral["id"]
    )
    submit_application(application["id"], student["id"])
    advance_cycle_to_phase(cycle["id"], "REVIEW")
    verification = create_income_verification(
        application["id"], make_counselor_headers(counselor["id"])
    )
    payload = decide_verification_payload("VERIFY")
    resp = api.decide_income_verification(
        verification["id"], payload,
        make_partner_staff_headers(referring_partner["id"]),
    )
    expect_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, payload)
    data, meta = validate_paginated(
        api.list_application_income_verifications(application["id"], _ADMIN)
    )
    assert meta["total_count"] == 1
    assert data[0]["outcome"] == "PENDING", (
        "the barred decision leaves the record pending"
    )
    decided = decide_verification(
        verification["id"], unrelated_partner["id"], "VERIFY"
    )
    assert decided["outcome"] == "VERIFIED"
    assert decided["decided_by_partner_id"] == unrelated_partner["id"]


def test_decide_verification_twice_returns_invalid_state(api):
    """PRD §3.6: "Decisions belong to `PartnerStaff` alone, acting with a
    `decision` of `VERIFY` or `WAIVE`, and only against a `PENDING` record —
    any other `outcome` is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/decide_verification_twice_returns_invalid_state
    """
    ctx = setup_submitted_application()
    advance_cycle_to_phase(ctx["cycle"]["id"], "REVIEW")
    counselor = create_counselor()
    partner = create_community_partner()
    verification = create_income_verification(
        ctx["application"]["id"], make_counselor_headers(counselor["id"])
    )
    decided = decide_verification(verification["id"], partner["id"], "VERIFY")
    assert decided["outcome"] == "VERIFIED", (
        "6200000 vs reported 6500000: 300,000 <= 650,000 (10%)"
    )
    payload = decide_verification_payload("WAIVE")
    resp = api.decide_income_verification(
        verification["id"], payload,
        make_partner_staff_headers(partner["id"]),
    )
    expect_error(resp, ApiErrorId.ERR_INVALID_STATE, payload)
    data, _meta = validate_paginated(
        api.list_application_income_verifications(
            ctx["application"]["id"], _ADMIN
        )
    )
    assert data[0]["outcome"] == "VERIFIED", (
        "the terminal decision is not overwritten"
    )


def test_create_cycle_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request whose `X-User-Role` header is absent or names no
    declared role, or whose `X-User-ID` header is absent for any role other
    than `Anonymous`, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/create_cycle_missing_auth_headers_returns_unauthenticated
    """
    payload = create_cycle_payload(name="No Auth Cycle")
    resp = api.create_cycle(payload, {})
    expect_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, payload)


def test_student_cannot_run_match_returns_unauthorized(api):
    """PRD §2.1: "A request whose role is not among an endpoint's authorized
    roles, or that fails the entity-backed ownership rule attached to that
    role, is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST | `/cycles/{id}/run-match` | Execute the binding match run
    (once per cycle) | ProgramAdmin".

    Design: Corner/rbac/student_cannot_run_match_returns_unauthorized
    """
    reset_clock()
    cycle = create_cycle()
    student = create_student()
    resp = api.run_match(cycle["id"], make_student_headers(student["id"]))
    expect_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_counselor_cannot_decide_verification_returns_unauthorized(api):
    """PRD §3.6: "Decisions belong to `PartnerStaff` alone, acting with a
    `decision` of `VERIFY` or `WAIVE`, and only against a `PENDING` record —
    any other `outcome` is `ERR_INVALID_STATE`."
    PRD §2.1: "A request whose role is not among an endpoint's authorized
    roles, or that fails the entity-backed ownership rule attached to that
    role, is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/counselor_cannot_decide_verification_returns_unauthorized
    """
    ctx = setup_submitted_application()
    advance_cycle_to_phase(ctx["cycle"]["id"], "REVIEW")
    counselor = create_counselor()
    create_community_partner()
    verification = create_income_verification(
        ctx["application"]["id"], make_counselor_headers(counselor["id"])
    )
    payload = decide_verification_payload("VERIFY")
    resp = api.decide_income_verification(
        verification["id"], payload,
        make_counselor_headers(counselor["id"]),
    )
    expect_error(resp, ApiErrorId.ERR_UNAUTHORIZED, payload)
    data, _meta = validate_paginated(
        api.list_application_income_verifications(
            ctx["application"]["id"], _ADMIN
        )
    )
    assert data[0]["outcome"] == "PENDING"


def test_student_b_cannot_submit_rankings_for_student_a(api):
    """PRD §2.1: "When `X-User-Role` is `Student`, `X-User-ID` is the `id` of
    the acting Student; ownership checks on any resource that references a
    Student compare the resource's student foreign key to `X-User-ID`, so a
    student may act only on their own applications, rankings, and enrollment
    acceptance."
    PRD §2.1: "A request whose role is not among an endpoint's authorized
    roles, or that fails the entity-backed ownership rule attached to that
    role, is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/student_b_cannot_submit_rankings_for_student_a
    """
    ctx = setup_finalist_application()
    college = create_college()
    student_b = create_student()
    advance_cycle_to_phase(ctx["cycle"]["id"], "RANKING")
    set_clock(CLOCK_IN_RANKING_WINDOW)
    payload = submit_rankings_payload(
        [ranking_entry(college["id"], 1)], ctx["application_version"]
    )
    resp = api.submit_rankings(
        ctx["application"]["id"], payload,
        make_student_headers(student_b["id"]),
    )
    expect_error(resp, ApiErrorId.ERR_UNAUTHORIZED, payload)
    assert get_current_rankings(ctx["application"]["id"]) == [], (
        "the ownership rejection creates no ranking rows"
    )
    assert get_application(ctx["application"]["id"])["status"] == "FINALIST"
