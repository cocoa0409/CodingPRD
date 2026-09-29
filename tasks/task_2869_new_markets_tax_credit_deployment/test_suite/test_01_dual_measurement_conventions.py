"""Two conventions measuring the same facts, and the disagreement is the point.

The substantially-all requirement is measured both by direct tracing and on a
time-weighted aggregate basis; community-benefits achievement is measured
either by headcount or by payroll hours.  Which of the two answers governs is
fixed by the award or by the agreement, never chosen by the caller.
"""
from test_helpers import (
    REVIEWER_CBA_USER_ID,
    REVIEWER_ELIGIBILITY_USER_ID,
    SPONSOR_DELTA_USER_ID,
    SPONSOR_ECHO_USER_ID,
    annual_certification_payload,
    annual_test_payload,
    assert_instant,
    assert_pct,
    create_cba,
    create_qalicb,
    create_tract,
    deploy_qlici,
    file_job_report,
    get_success_data,
    make_reviewer_headers,
    read_award,
    read_cba,
    read_qei,
    run_eligibility_test,
    set_clock,
    setup_active_award,
    setup_issued_investment,
)

# --- The investment measured under both substantially-all conventions -------

AGGREGATE_AWARD = {
    "substantially_all_method": "AGGREGATE_BALANCE",
    "service_area_state_codes": ["MS", "LA"],
}
ISSUANCE_CLOCK = "2026-09-01T00:00:00.000Z"
LATE_PLACEMENT_CLOCK = "2026-11-30T00:00:00.000Z"
FIRST_YEAR_END = "2027-09-01T00:00:00.000Z"


def _investment_with_a_late_placement(api):
    """One investment of 100000000 cents whose only placement lands late."""
    scenario = setup_issued_investment(
        api,
        clock=ISSUANCE_CLOCK,
        certification_suffix="001",
        award_overrides=dict(AGGREGATE_AWARD),
    )
    set_clock(api, LATE_PLACEMENT_CLOCK)
    scenario.qlici = deploy_qlici(
        api,
        scenario.cde,
        scenario.qei,
        scenario.qalicb,
        principal_cents=85_000_000,
    )
    scenario.qlicis.append(scenario.qlici)
    set_clock(api, FIRST_YEAR_END)
    return scenario


def test_annual_test_stores_both_measurements_and_lets_the_award_convention_govern(api):
    """A placement made late in the window passes direct tracing and fails aggregate.

    PRD: "The test copies the award's `substantially_all_method` into its own
    `governing_method`, and sets `governing_pct` to `measured_pct_direct` when
    that method is `DIRECT_TRACING` and to `measured_pct_aggregate` when it is
    `AGGREGATE_BALANCE`."

    Design: Difficulty/dual_variant_calc/substantially_all_direct_vs_aggregate_diverge_on_late_deployed_qlici
    """
    scenario = _investment_with_a_late_placement(api)

    test = get_success_data(
        api.run_annual_test(
            scenario.qei["id"],
            annual_test_payload(1),
            scenario.annual_reviewer_headers,
        )
    )

    assert_instant(test["window_start_at"], ISSUANCE_CLOCK, "window_start_at")
    assert_instant(test["window_end_at"], FIRST_YEAR_END, "window_end_at")
    assert test["window_days"] == 365, "a year is exactly 365 days"
    assert_pct(test["measured_pct_direct"], 89.47, "measured_pct_direct")
    assert_pct(test["measured_pct_aggregate"], 64.04, "measured_pct_aggregate")
    assert test["governing_method"] == "AGGREGATE_BALANCE"
    assert_pct(test["governing_pct"], 64.04, "governing_pct")
    assert test["result"] == "FAIL", "the governing figure is below 85.00"
    assert test["recapture_triggered"] is False
    assert test["breached_obligation_count"] == 0
    assert test["recertification_swept_qalicb_count"] == 0


def test_failing_the_governing_measurement_puts_the_investment_at_risk(api):
    """The failure opens a 180-day cure deadline and counts once against the award.

    PRD: "On a failing test an investment in `COMPLIANT` moves to `AT_RISK`
    with `cure_deadline_at` set to the logical clock advanced by 180 days."

    Design: Difficulty/dual_variant_calc/substantially_all_direct_vs_aggregate_diverge_on_late_deployed_qlici
    """
    scenario = _investment_with_a_late_placement(api)

    get_success_data(
        api.run_annual_test(
            scenario.qei["id"],
            annual_test_payload(1),
            scenario.annual_reviewer_headers,
        )
    )

    qei = read_qei(api, scenario.qei["id"])
    assert qei["compliance_status"] == "AT_RISK"
    assert_instant(qei["cure_deadline_at"], "2028-02-28T00:00:00.000Z", "cure_deadline_at")
    assert qei["compliance_years_completed"] == 1
    assert_pct(qei["substantially_all_pct_direct"], 89.47, "substantially_all_pct_direct")
    assert_pct(qei["substantially_all_pct_aggregate"], 64.04, "substantially_all_pct_aggregate")

    award = read_award(api, scenario.award["id"])
    assert award["at_risk_qei_count"] == 1
    assert award["recaptured_qei_count"] == 0
    assert award["compliance_posture"] == "UNRESTRICTED", (
        "one at-risk investment is short of the two that restrict an award"
    )


# --- The same two reporting periods measured on both job-quality bases ------

FIRST_PERIOD = ("2026-09-01T00:00:00.000Z", "2027-02-28T00:00:00.000Z")
SECOND_PERIOD = ("2027-03-01T00:00:00.000Z", "2027-08-31T00:00:00.000Z")
WAGE_PASSING_PERIOD = {
    "headcount": 20,
    "qualifying_headcount": 18,
    "total_hours": 46000,
    "qualifying_hours": 45000,
    "local_hires": 12,
    "avg_hourly_wage_cents": 1950,
}
WAGE_FAILING_PERIOD = {
    "headcount": 10,
    "qualifying_headcount": 6,
    "total_hours": 20800,
    "qualifying_hours": 12480,
    "local_hires": 5,
    "avg_hourly_wage_cents": 1750,
}


def _two_agreements_over_identical_evidence(api):
    """Two businesses, identical job reports, agreements on opposite bases."""
    scenario = setup_active_award(
        api, clock=ISSUANCE_CLOCK, certification_suffix="002"
    )
    tract = create_tract(api)
    headcount_business = create_qalicb(
        api,
        tract,
        sponsor_user_id=SPONSOR_DELTA_USER_ID,
        legal_name="Delta Foods LLC",
        naics_code="311412",
    )
    hours_business = create_qalicb(
        api,
        tract,
        sponsor_user_id=SPONSOR_ECHO_USER_ID,
        legal_name="Delta Fabrication LLC",
        naics_code="332312",
    )
    run_eligibility_test(
        api, headcount_business, reviewer_user_id=REVIEWER_ELIGIBILITY_USER_ID
    )
    run_eligibility_test(
        api, hours_business, reviewer_user_id=REVIEWER_ELIGIBILITY_USER_ID
    )
    headcount_cba = create_cba(
        api,
        scenario.cde,
        headcount_business,
        scenario.award,
        measurement_basis="HEADCOUNT",
    )
    hours_cba = create_cba(
        api,
        scenario.cde,
        hours_business,
        scenario.award,
        measurement_basis="PAYROLL_HOURS",
    )
    set_clock(api, FIRST_YEAR_END)
    for agreement, sponsor in (
        (headcount_cba, SPONSOR_DELTA_USER_ID),
        (hours_cba, SPONSOR_ECHO_USER_ID),
    ):
        file_job_report(
            api,
            agreement,
            FIRST_PERIOD[0],
            FIRST_PERIOD[1],
            sponsor_user_id=sponsor,
            **WAGE_PASSING_PERIOD,
        )
        file_job_report(
            api,
            agreement,
            SECOND_PERIOD[0],
            SECOND_PERIOD[1],
            sponsor_user_id=sponsor,
            **WAGE_FAILING_PERIOD,
        )
    scenario.extras["headcount_cba"] = headcount_cba
    scenario.extras["hours_cba"] = hours_cba
    return scenario


def _certify_first_year(api, agreement):
    return get_success_data(
        api.certify_community_benefits(
            agreement["id"],
            annual_certification_payload(1, ISSUANCE_CLOCK, FIRST_YEAR_END),
            make_reviewer_headers(REVIEWER_CBA_USER_ID),
        )
    )


def test_headcount_and_payroll_hours_bases_score_the_same_reports_differently(api):
    """Eighteen qualifying heads score 72.00 while their 45000 hours score 86.52.

    PRD: "The two bases genuinely disagree, and the disagreement is the point:
    a part-time-heavy project reports many hours across few heads and scores
    lower under `HEADCOUNT` than under `PAYROLL_HOURS` — against a target of
    25, eighteen qualifying heads and 45000 qualifying hours produce 72.00
    percent on the headcount basis and 86.52 percent on the payroll-hours
    basis."

    Design: Difficulty/dual_variant_calc/job_quality_headcount_vs_payroll_hours_diverge_on_same_reports
    """
    scenario = _two_agreements_over_identical_evidence(api)

    by_headcount = _certify_first_year(api, scenario.extras["headcount_cba"])
    by_hours = _certify_first_year(api, scenario.extras["hours_cba"])

    assert by_headcount["measurement_basis"] == "HEADCOUNT"
    assert by_headcount["certification_year"] == 1
    assert_pct(by_headcount["achieved_fte"], 18, "achieved_fte on the headcount basis")
    assert_pct(by_headcount["compliance_pct"], 72.00, "compliance_pct on the headcount basis")
    assert by_headcount["classification"] == "SHORTFALL"
    assert by_headcount["resulting_status"] == "BREACHED"

    assert by_hours["measurement_basis"] == "PAYROLL_HOURS"
    assert_pct(by_hours["achieved_fte"], 21.63, "achieved_fte on the payroll-hours basis")
    assert_pct(by_hours["compliance_pct"], 86.52, "compliance_pct on the payroll-hours basis")
    assert by_hours["classification"] == "CURE_REQUIRED"
    assert by_hours["resulting_status"] == "CURE_REQUIRED"

    for response in (by_headcount, by_hours):
        assert response["report_count"] == 2
        assert response["excluded_wage_failing_report_count"] == 1, (
            "the underpaying period is dropped from the job-quality numerator"
        )
        assert_pct(response["local_hire_pct"], 56.67, "local_hire_pct")


def test_the_two_bases_drive_the_agreements_to_different_states_and_restrict_the_award(api):
    """One agreement breaches on a shortfall, the other only enters its cure year.

    PRD: "Otherwise, if the award has at least two investments whose
    `compliance_status` is `AT_RISK`, or at least one community benefits
    agreement in `BREACHED`, the posture is `RESTRICTED`, which bars new
    investment issuance while still permitting sub-allocations from investments
    already issued."

    Design: Difficulty/dual_variant_calc/job_quality_headcount_vs_payroll_hours_diverge_on_same_reports
    """
    scenario = _two_agreements_over_identical_evidence(api)

    _certify_first_year(api, scenario.extras["headcount_cba"])
    _certify_first_year(api, scenario.extras["hours_cba"])

    breached = read_cba(api, scenario.extras["headcount_cba"]["id"])
    assert breached["status"] == "BREACHED"
    assert_pct(breached["latest_compliance_pct"], 72.00, "latest_compliance_pct")
    assert_pct(breached["latest_local_hire_pct"], 56.67, "latest_local_hire_pct")

    curing = read_cba(api, scenario.extras["hours_cba"]["id"])
    assert curing["status"] == "CURE_REQUIRED"
    assert curing["consecutive_cure_required_count"] == 1
    assert_pct(curing["latest_compliance_pct"], 86.52, "latest_compliance_pct")

    award = read_award(api, scenario.award["id"])
    assert award["cba_breach_count"] == 1
    assert award["compliance_posture"] == "RESTRICTED"
    assert award["lifecycle_status"] == "ACTIVE"
