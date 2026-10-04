"""Benefit continuation and pension accrual: the pinned per-period-then-sum
rounding order against the aggregate variant, the 24-month health cap
boundary, and the one-assessment-per-case rule."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    add_case_note,
    assert_benefit_assessment,
    assert_two_dp,
    create_benefit_assessment,
    create_case,
    create_employer,
    create_member,
    create_service_period,
    set_clock,
    validate_error,
    validate_success,
)


def _setup_benefits_case(api: ApiClient, periods: list, **member_overrides) -> dict:
    """Employer + member + the given completed periods + a case."""
    case_overrides = member_overrides.pop(
        "case_overrides", {"issue_type": "BENEFITS", "description": "Benefit questions"}
    )
    employer = create_employer(api)
    member = create_member(api, **member_overrides)
    for period in periods:
        create_service_period(api, member["id"], employer["id"], **period)
    case = create_case(api, member["id"], employer["id"], **case_overrides)
    return {"employer": employer, "member": member, "case": case}


def test_pension_credit_per_period_vs_aggregate_rounding_diverge(api: ApiClient, coordinator_headers: dict):
    """PRD §3.6: "The official figure, `pension_credit_months_official`, rounds per period first: each period's days are divided by 30.44 and rounded half-up to 2 decimal places, the per-period figures are summed, and the sum is rounded half-up to 2 decimal places. The informational comparison, `pension_credit_months_alternate`, aggregates first: all days are summed, divided by 30.44, and rounded half-up to 2 decimal places once."
    PRD §3.6: "The two diverge whenever per-period rounding accumulates differently — periods of 10, 20, and 30 days yield an official 0.33 + 0.66 + 0.99 = 1.98 against an alternate 60 / 30.44 = 1.97."

    Design: Difficulty/dual_variant_calc/pension_credit_per_period_vs_aggregate_rounding
    """
    set_clock(api)
    world = _setup_benefits_case(
        api,
        [
            {"start_date": "2026-01-01T00:00:00Z", "end_date": "2026-01-11T00:00:00Z", "orders_type": "DRILL"},
            {"start_date": "2026-02-01T00:00:00Z", "end_date": "2026-02-21T00:00:00Z", "orders_type": "ANNUAL_TRAINING"},
            {"start_date": "2026-03-01T00:00:00Z", "end_date": "2026-03-31T00:00:00Z", "orders_type": "ACTIVE_DUTY"},
        ],
        full_name="Sam Okafor", email="sam@example.com", branch="NAVY", component="NAVY_RESERVE",
    )

    assessment = create_benefit_assessment(api, world["case"]["id"], headers=coordinator_headers)
    assert_benefit_assessment(assessment)
    assert_two_dp(assessment["pension_credit_months_official"], 1.98, "pension_credit_months_official")
    assert_two_dp(assessment["pension_credit_months_alternate"], 1.97, "pension_credit_months_alternate")
    assert assessment["pension_credit_months_official"] != assessment["pension_credit_months_alternate"]


def test_pension_benefit_case_tracks_health_and_education(api: ApiClient, coordinator_headers: dict):
    """PRD §3.6: "Health continuation is computed in aggregate: the pair's total completed service days are divided by 30.44, the quotient is rounded half-up to 2 decimal places, and `health_continuation_months` is the lesser of that figure and 24"
    PRD §3.6: "`education_required` is true when the case's `issue_type` is `BENEFITS` or `PENSION`. `education_satisfied` is not stored but recomputed at every read: it is true when the case carries at least one `EMPLOYER_EDUCATION` note."

    Design: Difficulty/dual_variant_calc/pension_credit_per_period_vs_aggregate_rounding
    """
    set_clock(api)
    world = _setup_benefits_case(
        api,
        [
            {"start_date": "2026-01-01T00:00:00Z", "end_date": "2026-01-11T00:00:00Z", "orders_type": "DRILL"},
            {"start_date": "2026-02-01T00:00:00Z", "end_date": "2026-02-21T00:00:00Z", "orders_type": "ANNUAL_TRAINING"},
            {"start_date": "2026-03-01T00:00:00Z", "end_date": "2026-03-31T00:00:00Z", "orders_type": "ACTIVE_DUTY"},
        ],
        full_name="Sam Okafor", email="sam@example.com", branch="NAVY", component="NAVY_RESERVE",
    )

    assessment = create_benefit_assessment(api, world["case"]["id"], headers=coordinator_headers)
    assert_two_dp(assessment["health_continuation_months"], 1.97, "health_continuation_months")
    assert assessment["education_required"] is True, "a BENEFITS case carries the employer-education duty"
    assert assessment["education_satisfied"] is False, "no EMPLOYER_EDUCATION note exists yet"

    add_case_note(api, world["case"]["id"], "EMPLOYER_EDUCATION", "Employer educated on benefit duties.")
    reread = validate_success(api.list_benefit_assessments(world["case"]["id"], coordinator_headers))
    assert len(reread) == 1
    assert reread[0]["education_satisfied"] is True, "education_satisfied is recomputed at read time"


def test_pension_rounding_order_pinned_per_period_first(api: ApiClient, coordinator_headers: dict):
    """PRD §3.6: "The official figure, `pension_credit_months_official`, rounds per period first: each period's days are divided by 30.44 and rounded half-up to 2 decimal places, the per-period figures are summed, and the sum is rounded half-up to 2 decimal places."
    PRD §2.9: "Where a formula in §3 specifies per-step rounding, the stated rounding order is part of the rule and two rounding orders that differ are reported as two different values rather than reconciled."

    Design: Difficulty/combinatorial_formula/pension_rounding_order_pinned
    """
    set_clock(api)
    world = _setup_benefits_case(
        api,
        [
            {"start_date": "2026-01-01T00:00:00Z", "end_date": "2026-01-06T00:00:00Z", "orders_type": "DRILL"},
            {"start_date": "2026-02-01T00:00:00Z", "end_date": "2026-02-06T00:00:00Z", "orders_type": "DRILL"},
            {"start_date": "2026-03-01T00:00:00Z", "end_date": "2026-03-06T00:00:00Z", "orders_type": "DRILL"},
        ],
        full_name="Kit Reyes", email="kit@example.com", branch="MARINES", component="MARINE_RESERVE",
        case_overrides={"issue_type": "PENSION", "description": "Pension crediting dispute over drill weekends"},
    )

    assessment = create_benefit_assessment(api, world["case"]["id"], headers=coordinator_headers)
    assert_benefit_assessment(assessment)
    assert_two_dp(assessment["pension_credit_months_official"], 0.48,
                  "0.16 + 0.16 + 0.16 after per-period rounding")


def test_pension_aggregate_rounding_would_differ(api: ApiClient, coordinator_headers: dict):
    """PRD §3.6: "The informational comparison, `pension_credit_months_alternate`, aggregates first: all days are summed, divided by 30.44, and rounded half-up to 2 decimal places once."
    PRD §2.9: "Benefit mathematics in this system treats one month as exactly 30.44 days. Every month-valued result — health continuation, official pension credit, alternate pension credit — is expressed as a number rounded half-up to exactly 2 decimal places."

    Design: Difficulty/combinatorial_formula/pension_rounding_order_pinned
    """
    set_clock(api)
    world = _setup_benefits_case(
        api,
        [
            {"start_date": "2026-01-01T00:00:00Z", "end_date": "2026-01-06T00:00:00Z", "orders_type": "DRILL"},
            {"start_date": "2026-02-01T00:00:00Z", "end_date": "2026-02-06T00:00:00Z", "orders_type": "DRILL"},
            {"start_date": "2026-03-01T00:00:00Z", "end_date": "2026-03-06T00:00:00Z", "orders_type": "DRILL"},
        ],
        full_name="Kit Reyes", email="kit@example.com", branch="MARINES", component="MARINE_RESERVE",
        case_overrides={"issue_type": "PENSION", "description": "Pension crediting dispute over drill weekends"},
    )

    assessment = create_benefit_assessment(api, world["case"]["id"], headers=coordinator_headers)
    assert_two_dp(assessment["pension_credit_months_alternate"], 0.49, "round(15 / 30.44, 2) aggregated")
    assert assessment["pension_credit_months_official"] < assessment["pension_credit_months_alternate"], \
        "per-period rounding applied before summation yields the smaller official figure here"


def test_health_continuation_cap_boundary_at_24_months(api: ApiClient, coordinator_headers: dict):
    """PRD §3.6: "Health continuation is computed in aggregate: the pair's total completed service days are divided by 30.44, the quotient is rounded half-up to 2 decimal places, and `health_continuation_months` is the lesser of that figure and 24 — the statutory cap binds only above 24, so a raw figure of exactly 24 stands uncapped."
    PRD §3.6: "Unlike the service cap, pension and health math counts every completed period, chargeable and cap-exempt alike."

    Design: Corner/calculations/health_continuation_cap_boundary_at_24_months
    """
    set_clock(api)
    employer = create_employer(api)
    member_x = create_member(api, full_name="Xu Lan", email="xu@example.com")
    create_service_period(api, member_x["id"], employer["id"],
                          start_date="2024-01-01T00:00:00Z", end_date="2026-01-01T00:00:00Z",
                          orders_type="ACTIVE_DUTY")
    case_x = create_case(api, member_x["id"], employer["id"], issue_type="BENEFITS",
                         description="Health continuation at cap")
    member_y = create_member(api, full_name="Yan Mei", email="yan@example.com")
    create_service_period(api, member_y["id"], employer["id"],
                          start_date="2024-01-01T00:00:00Z", end_date="2025-12-31T00:00:00Z",
                          orders_type="ACTIVE_DUTY")
    case_y = create_case(api, member_y["id"], employer["id"], issue_type="BENEFITS",
                         description="Health continuation below cap")

    assessment_x = create_benefit_assessment(api, case_x["id"], headers=coordinator_headers)
    assert_two_dp(assessment_x["health_continuation_months"], 24, "731 days round to 24.01, capped to 24")
    assert_two_dp(assessment_x["pension_credit_months_official"], 24.01,
                  "pension credit is not capped - only health continuation is")

    assessment_y = create_benefit_assessment(api, case_y["id"], headers=coordinator_headers)
    assert_two_dp(assessment_y["health_continuation_months"], 23.98, "730 days round to 23.98, below the cap")


def test_second_benefit_assessment_for_same_case_rejected(api: ApiClient, coordinator_headers: dict):
    """PRD §3.6: "A case supports at most one `BenefitAssessment`; a second attempt for the same case is rejected with `ERR_INVALID_STATE`."
    PRD §3.6: "Reading a case's assessments returns an array of zero or one element, and is open to all four case parties."

    Design: Corner/endpoints/second_benefit_assessment_for_same_case_rejected
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)
    create_service_period(api, member["id"], employer["id"],
                          start_date="2026-01-01T00:00:00Z", end_date="2026-02-01T00:00:00Z",
                          orders_type="ACTIVE_DUTY")
    case = create_case(api, member["id"], employer["id"], description="Refused reinstatement",
                       application_submitted_at="2026-04-20T00:00:00Z")

    first = create_benefit_assessment(api, case["id"], headers=coordinator_headers)
    assert_benefit_assessment(first)

    duplicate = api.create_benefit_assessment({"case_id": case["id"]}, coordinator_headers)
    validate_error(duplicate, ApiErrorId.ERR_INVALID_STATE)

    listing = validate_success(api.list_benefit_assessments(case["id"], coordinator_headers))
    assert len(listing) == 1 and listing[0]["id"] == first["id"], "the first assessment is untouched"
