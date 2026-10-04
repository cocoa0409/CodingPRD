"""Submission screens: household income cap boundaries, the prep-alumni
academic waiver, the need-tier half-cap boundary, and the submit state gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_application,
    complete_prep_program,
    create_application,
    create_student,
    expect_error,
    get_application,
    make_student_headers,
    setup_application_open,
    setup_draft_application,
    setup_submitted_application,
    submit_application,
)

_ADMIN = TEST_USERS["program_admin_headers"]


def test_income_exactly_at_cap_is_eligible(api):
    """PRD §3.3: "The cap starts at $65,000 — 6,500,000 cents — for a
    reference household of four and adjusts by $4,000, that is 400,000 cents,
    for each household member above or below four; a household of six is
    capped at $73,000 and a household of two at $57,000. Eligibility requires
    `household_income_cents` to be no more than the cap computed for the
    applicant's `household_size`, and income exactly equal to the cap is
    eligible."

    Design: Difficulty/boundary_precision_check/income_exactly_at_cap_eligible_one_cent_over_rejected
    """
    # Default application payload carries income 6,500,000 for a household of
    # 4 — exactly the cap.
    ctx = setup_draft_application()
    submitted = submit_application(
        ctx["application"]["id"], ctx["student"]["id"]
    )
    assert_application(submitted)
    assert submitted["status"] == "UNDER_REVIEW", (
        "income exactly equal to the cap is eligible"
    )


def test_income_one_cent_over_cap_is_rejected(api):
    """PRD §3.3: "Income above the cap is rejected with
    `ERR_INCOME_INELIGIBLE`. The comparison is exact integer arithmetic with
    no rounding."

    Design: Difficulty/boundary_precision_check/income_exactly_at_cap_eligible_one_cent_over_rejected
    """
    ctx = setup_draft_application(
        app_overrides={"household_income_cents": 6_500_001}
    )
    resp = api.submit_application(
        ctx["application"]["id"], make_student_headers(ctx["student"]["id"])
    )
    expect_error(resp, ApiErrorId.ERR_INCOME_INELIGIBLE)
    refreshed = get_application(ctx["application"]["id"])
    assert refreshed["status"] == "DRAFT", (
        "a rejected submit leaves the application in DRAFT"
    )


def test_household_cap_scales_with_household_size(api):
    """PRD §3.3: "The cap starts at $65,000 — 6,500,000 cents — for a
    reference household of four and adjusts by $4,000, that is 400,000 cents,
    for each household member above or below four; a household of six is
    capped at $73,000 and a household of two at $57,000."
    PRD §3.3: "Eligibility requires `household_income_cents` to be no more
    than the cap computed for the applicant's `household_size`, and income
    exactly equal to the cap is eligible. Income above the cap is rejected
    with `ERR_INCOME_INELIGIBLE`."

    Design: Corner/calculations/household_cap_scales_with_household_size
    """
    ctx = setup_application_open()
    cycle_id = ctx["cycle"]["id"]
    student_a = create_student()
    app_a = create_application(
        student_a["id"], cycle_id, household_income_cents=5_700_000, household_size=2
    )
    student_b = create_student()
    app_b = create_application(
        student_b["id"], cycle_id, household_income_cents=5_700_001, household_size=2
    )
    submitted = submit_application(app_a["id"], student_a["id"])
    assert submitted["status"] == "UNDER_REVIEW", (
        "size-2 cap is 6,500,000 - 2*400,000 == 5,700,000; at-cap is eligible"
    )
    resp = api.submit_application(app_b["id"], make_student_headers(student_b["id"]))
    expect_error(resp, ApiErrorId.ERR_INCOME_INELIGIBLE)


def test_academic_prep_waiver_vs_standard_path(api):
    """PRD §3.3: "A prep alumnus qualifies on grades alone: a `gpa_scaled` of
    at least 330, with the test requirement waived entirely. Every other
    applicant must present a `gpa_scaled` of at least 350 and a non-null
    `test_score` of at least 1200. Every comparison in the screen is inclusive
    of its boundary, and failure is rejected with `ERR_ACADEMIC_INELIGIBLE`."
    PRD §3.3: "`prep_alum` is true exactly when the student has at least one
    `COMPLETED` prep record at that moment — `ENROLLED` and `WITHDRAWN`
    records do not count — and because the flag is a snapshot, a prep program
    completed later never rewrites an already-submitted application."

    Design: Corner/calculations/academic_prep_waiver_vs_standard_path
    """
    ctx = setup_application_open()
    cycle_id = ctx["cycle"]["id"]
    alum = create_student()
    complete_prep_program(alum["id"])
    app_alum = create_application(
        alum["id"], cycle_id, gpa_scaled=335, test_score=None
    )
    non_alum = create_student()
    app_non_alum = create_application(
        non_alum["id"], cycle_id, gpa_scaled=335, test_score=1300
    )
    submitted = submit_application(app_alum["id"], alum["id"])
    assert submitted["status"] == "UNDER_REVIEW"
    assert submitted["prep_alum"] is True
    assert submitted["academic_index"] == 670, (
        f"335*2 + 0 (null test) == 670, got {submitted['academic_index']!r}"
    )
    resp = api.submit_application(
        app_non_alum["id"], make_student_headers(non_alum["id"])
    )
    expect_error(resp, ApiErrorId.ERR_ACADEMIC_INELIGIBLE)


def test_need_tier_half_cap_boundary(api):
    """PRD §3.3: "`need_tier` compares income against half the household cap:
    the cap from the income screen is halved and that half is rounded half-up
    to a whole cent; income at or below the half yields `HIGH`, and anything
    above it yields `STANDARD`."

    Design: Corner/calculations/need_tier_half_cap_boundary
    """
    ctx = setup_application_open()
    cycle_id = ctx["cycle"]["id"]
    student_a = create_student()
    app_a = create_application(
        student_a["id"], cycle_id, household_income_cents=3_250_000
    )
    student_b = create_student()
    app_b = create_application(
        student_b["id"], cycle_id, household_income_cents=3_250_001
    )
    sub_a = submit_application(app_a["id"], student_a["id"])
    assert sub_a["need_tier"] == "HIGH", (
        "half the size-4 cap is exactly 3,250,000; at the half yields HIGH"
    )
    sub_b = submit_application(app_b["id"], student_b["id"])
    assert sub_b["need_tier"] == "STANDARD", (
        "one cent above the half yields STANDARD"
    )


def test_submit_twice_returns_invalid_state(api):
    """PRD §3.3: "Submission moves an application `DRAFT` → `UNDER_REVIEW` and
    is guarded by five screens evaluated in the global order of §2.10: the
    application must currently be `DRAFT` (`ERR_INVALID_STATE`); ..."
    PRD §3.3: "A successful submit stamps `submitted_at` from the logical
    clock, flips the cited referral (when there is one) from `NOMINATED` to
    `CONVERTED`, advances the student's `student_stage` to `APPLICANT`, and
    increments the application's `version`."

    Design: Corner/state_machines/submit_twice_returns_invalid_state
    """
    ctx = setup_submitted_application()
    first_submitted_at = ctx["application"]["submitted_at"]
    assert first_submitted_at, "first submit must stamp submitted_at"
    resp = api.submit_application(
        ctx["application"]["id"], make_student_headers(ctx["student"]["id"])
    )
    expect_error(resp, ApiErrorId.ERR_INVALID_STATE)
    refreshed = get_application(ctx["application"]["id"])
    assert refreshed["status"] == "UNDER_REVIEW"
    assert refreshed["submitted_at"] == first_submitted_at, (
        "the rejected second submit must not move submitted_at"
    )
