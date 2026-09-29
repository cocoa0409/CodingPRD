"""Thresholds evaluated at the boundary, and a measurement over nothing at all.

Exactly 85.00 percent passes the substantially-all test while 84.95 fails it, and
a certification window holding no evidence scores zero rather than dividing by
zero.
"""
from test_helpers import (
    assert_cents,
    assert_instant,
    assert_pct,
    certify_community_benefits,
    close_fund,
    create_cba,
    create_fund,
    deploy_qlici,
    issue_qei,
    make_agency_headers,
    read_award,
    read_cba,
    read_qalicb,
    read_qei,
    read_qlici,
    run_annual_test,
    set_clock,
    setup_active_award,
    setup_certified_project_company,
    setup_deployed_investment,
    validate_paginated,
)

ISSUANCE_CLOCK = "2026-09-01T00:00:00.000Z"
FIRST_YEAR_END = "2027-09-01T00:00:00.000Z"
CURE_DEADLINE = "2028-02-28T00:00:00.000Z"

#: 80750000 over a net deployable 95000000 is exactly 85.00 percent.
PRINCIPAL_AT_THE_LINE = 80_750_000
#: 80700000 over the same denominator is 84.95 percent.
PRINCIPAL_BELOW_THE_LINE = 80_700_000


def _two_investments_either_side_of_the_threshold(api):
    scenario = setup_deployed_investment(
        api,
        clock=ISSUANCE_CLOCK,
        certification_suffix="010",
        fund_overrides={"legal_name": "NMTC Fund A LLC"},
        qlici_overrides={"principal_cents": PRINCIPAL_AT_THE_LINE},
    )
    fund_b = close_fund(api, create_fund(api, legal_name="NMTC Fund B LLC"))
    scenario.award = read_award(api, scenario.award["id"])
    qei_b = issue_qei(api, scenario.cde, scenario.award, fund_b)
    qlici_b = deploy_qlici(
        api,
        scenario.cde,
        qei_b,
        scenario.qalicb,
        principal_cents=PRINCIPAL_BELOW_THE_LINE,
    )
    scenario.extras["qei_b"] = qei_b
    scenario.extras["qlici_b"] = qlici_b

    set_clock(api, FIRST_YEAR_END)
    scenario.extras["test_a"] = run_annual_test(api, scenario.qei, 1)
    scenario.extras["test_b"] = run_annual_test(api, qei_b, 1)
    return scenario


def test_a_ratio_of_exactly_85_00_percent_passes_the_annual_test(api):
    """The threshold is inclusive, so the investment at the line stays compliant.

    PRD: "The compliance threshold is 85.00 and it is inclusive — exactly 85.00
    passes, and 84.99 fails."

    PRD: "The `result` is `PASS` when the `governing_pct` is at least 85.00 *and*
    the test's `breached_obligation_count` is 0; otherwise it is `FAIL`."

    Design: Difficulty/boundary_precision_check/substantially_all_direct_ratio_at_exactly_85_00_passes_while_84_95_fails
    """
    scenario = _two_investments_either_side_of_the_threshold(api)
    test_a = scenario.extras["test_a"]

    assert_pct(test_a["measured_pct_direct"], 85.00, "measured_pct_direct")
    assert test_a["governing_method"] == "DIRECT_TRACING"
    assert_pct(test_a["governing_pct"], 85.00, "governing_pct")
    assert test_a["breached_obligation_count"] == 0
    assert test_a["result"] == "PASS"
    assert_instant(test_a["window_start_at"], ISSUANCE_CLOCK, "window_start_at")
    assert_instant(test_a["window_end_at"], FIRST_YEAR_END, "window_end_at")
    assert test_a["window_days"] == 365

    qei = read_qei(api, scenario.qei["id"])
    assert qei["compliance_status"] == "COMPLIANT"
    assert qei["cure_deadline_at"] is None
    assert qei["compliance_years_completed"] == 1


def test_a_ratio_of_84_95_percent_fails_and_opens_a_180_day_cure_deadline(api):
    """Five hundredths of a percent below the line is a failure like any other.

    PRD: "On a failing test an investment in `COMPLIANT` moves to `AT_RISK` with
    `cure_deadline_at` set to the logical clock advanced by 180 days."

    Design: Difficulty/boundary_precision_check/substantially_all_direct_ratio_at_exactly_85_00_passes_while_84_95_fails
    """
    scenario = _two_investments_either_side_of_the_threshold(api)
    test_b = scenario.extras["test_b"]

    assert_pct(test_b["measured_pct_direct"], 84.95, "measured_pct_direct")
    assert_pct(test_b["governing_pct"], 84.95, "governing_pct")
    assert test_b["result"] == "FAIL"
    assert test_b["recapture_triggered"] is False

    qei_b = read_qei(api, scenario.extras["qei_b"]["id"])
    assert qei_b["compliance_status"] == "AT_RISK"
    assert_instant(qei_b["cure_deadline_at"], CURE_DEADLINE, "cure_deadline_at")
    assert qei_b["compliance_years_completed"] == 1


def test_one_at_risk_investment_of_two_leaves_the_award_unrestricted(api):
    """The restricting clause needs two at-risk investments, not one.

    PRD: "Otherwise, if the award has at least two investments whose
    `compliance_status` is `AT_RISK`, or at least one community benefits agreement
    in `BREACHED`, the posture is `RESTRICTED`, which bars new investment issuance
    while still permitting sub-allocations from investments already issued."

    Design: Difficulty/boundary_precision_check/substantially_all_direct_ratio_at_exactly_85_00_passes_while_84_95_fails
    """
    scenario = _two_investments_either_side_of_the_threshold(api)

    award = read_award(api, scenario.award["id"])
    assert award["at_risk_qei_count"] == 1
    assert award["recaptured_qei_count"] == 0
    assert award["compliance_posture"] == "UNRESTRICTED"

    assert scenario.extras["test_a"]["recertification_swept_qalicb_count"] == 0
    assert scenario.extras["test_b"]["recertification_swept_qalicb_count"] == 0
    assert read_qalicb(api, scenario.qalicb["id"])["eligibility_status"] == "CERTIFIED"
    assert_cents(
        read_qlici(api, scenario.qlici["id"])["outstanding_principal_cents"],
        PRINCIPAL_AT_THE_LINE,
        "outstanding_principal_cents",
    )


# --- A certification window with no evidence in it -------------------------

CERTIFICATION_CLOCK = FIRST_YEAR_END
WINDOW_START = ISSUANCE_CLOCK
WINDOW_END = FIRST_YEAR_END


def _agreement_with_no_job_reports(api):
    scenario = setup_active_award(
        api, clock=ISSUANCE_CLOCK, certification_suffix="011"
    )
    setup_certified_project_company(api, scenario)
    scenario.cba = create_cba(api, scenario.cde, scenario.qalicb, scenario.award)
    set_clock(api, CERTIFICATION_CLOCK)
    return scenario


def test_certifying_an_empty_window_scores_zero_instead_of_refusing_the_request(api):
    """No reports means an achieved figure of zero, not a division by zero.

    PRD: "A window containing no reports at all yields an `achieved_fte` of 0, a
    `compliance_pct` of 0.00, a `local_hire_pct` of 0.00 and therefore an
    immediate `SHORTFALL`."

    Design: Difficulty/boundary_precision_check/job_quality_certification_over_an_empty_report_set_yields_zero_not_a_division_error
    """
    scenario = _agreement_with_no_job_reports(api)

    _rows, meta = validate_paginated(
        api.list_job_reports(scenario.cba["id"], make_agency_headers())
    )
    assert meta["total_count"] == 0

    certification = certify_community_benefits(
        api, scenario.cba, 1, WINDOW_START, WINDOW_END
    )

    assert certification["certification_year"] == 1
    assert certification["measurement_basis"] == "HEADCOUNT"
    assert certification["report_count"] == 0
    assert certification["excluded_wage_failing_report_count"] == 0
    assert_pct(certification["achieved_fte"], 0, "achieved_fte")
    assert_pct(certification["compliance_pct"], 0.00, "compliance_pct")
    assert_pct(certification["local_hire_pct"], 0.00, "local_hire_pct")
    assert certification["classification"] == "SHORTFALL"
    assert certification["resulting_status"] == "BREACHED"


def test_the_empty_shortfall_breaches_the_agreement_and_restricts_the_award(api):
    """A shortfall is a breach, and one breach is enough to restrict the award.

    PRD: "A `SHORTFALL` moves the agreement to `BREACHED` with `breached_at`
    stamped from the logical clock."

    PRD: "Otherwise, if the award has at least two investments whose
    `compliance_status` is `AT_RISK`, or at least one community benefits agreement
    in `BREACHED`, the posture is `RESTRICTED`, which bars new investment issuance
    while still permitting sub-allocations from investments already issued."

    Design: Difficulty/boundary_precision_check/job_quality_certification_over_an_empty_report_set_yields_zero_not_a_division_error
    """
    scenario = _agreement_with_no_job_reports(api)

    certify_community_benefits(api, scenario.cba, 1, WINDOW_START, WINDOW_END)

    agreement = read_cba(api, scenario.cba["id"])
    assert agreement["status"] == "BREACHED"
    assert_instant(agreement["breached_at"], CERTIFICATION_CLOCK, "breached_at")
    assert_pct(agreement["latest_compliance_pct"], 0.00, "latest_compliance_pct")
    assert_pct(agreement["latest_local_hire_pct"], 0.00, "latest_local_hire_pct")

    award = read_award(api, scenario.award["id"])
    assert award["cba_breach_count"] == 1
    assert award["compliance_posture"] == "RESTRICTED"
