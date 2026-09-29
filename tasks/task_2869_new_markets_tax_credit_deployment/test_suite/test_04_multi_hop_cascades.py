"""Cascades that travel several hops inside a single request.

One failing eligibility test reaches from a project company through its
sub-allocations and their parent investments all the way to the award's posture;
one failing annual test reaches from an investment's clawback to an award freeze
that blocks the next placement.
"""
from test_helpers import (
    ApiErrorId,
    assert_cents,
    assert_instant,
    assert_pct,
    close_fund,
    create_fund,
    create_qlici_payload,
    deploy_qlici,
    issue_qei,
    read_award,
    read_cba,
    read_qalicb,
    read_qei,
    read_qlici,
    run_annual_test,
    run_eligibility_test,
    set_clock,
    setup_at_risk_investment,
    setup_deployed_investment,
    validate_error,
)

ISSUANCE_CLOCK = "2026-09-01T00:00:00.000Z"
FAILURE_CLOCK = "2026-10-01T00:00:00.000Z"
CURE_DEADLINE_FROM_FAILURE = "2027-03-30T00:00:00.000Z"
FAILING_PRONGS = {"gross_income_lic_pct": 48.00, "collectibles_pct": 6.00}


def _two_investments_funding_one_company(api):
    """Two investments of the same award, each with one placement in one business."""
    scenario = setup_deployed_investment(
        api, clock=ISSUANCE_CLOCK, certification_suffix="006"
    )
    second_fund = create_fund(api, legal_name="NMTC Fund II LLC")
    second_fund = close_fund(api, second_fund)
    scenario.award = read_award(api, scenario.award["id"])
    second_qei = issue_qei(api, scenario.cde, scenario.award, second_fund)
    second_qlici = deploy_qlici(api, scenario.cde, second_qei, scenario.qalicb)

    scenario.extras["second_fund"] = second_fund
    scenario.extras["second_qei"] = second_qei
    scenario.qlicis.append(second_qlici)
    scenario.award = read_award(api, scenario.award["id"])
    return scenario


def _fail_the_company(api, scenario):
    set_clock(api, FAILURE_CLOCK)
    return run_eligibility_test(api, scenario.qalicb, **FAILING_PRONGS)


def test_a_failing_eligibility_test_stops_every_placement_in_that_company_qualifying(api):
    """Hop one of the disqualification cascade reaches both sub-allocations.

    PRD: "**Hop one:** every sub-allocation of this business whose `status` is
    `DEPLOYED` or `PARTIALLY_REPAID` moves to `NON_QUALIFYING` with
    `non_qualifying_since_at` stamped from the logical clock, and its principal
    leaves every substantially-all numerator."

    Design: Difficulty/transitive_cascade/eligibility_failure_cascades_qalicb_to_qlicis_to_qeis_to_award_posture
    """
    scenario = _two_investments_funding_one_company(api)

    test = _fail_the_company(api, scenario)
    assert test["result"] == "FAIL"

    company = read_qalicb(api, scenario.qalicb["id"])
    assert company["eligibility_status"] == "FAILED"
    assert company["consecutive_failed_test_count"] == 1

    for placement in scenario.qlicis:
        row = read_qlici(api, placement["id"])
        assert row["status"] == "NON_QUALIFYING"
        assert_instant(
            row["non_qualifying_since_at"], FAILURE_CLOCK, "non_qualifying_since_at"
        )
        assert_cents(
            row["outstanding_principal_cents"], 85_000_000, "outstanding_principal_cents"
        )


def test_both_parent_investments_fall_to_zero_percent_and_become_at_risk(api):
    """Hop two re-measures each parent investment under direct tracing.

    PRD: "**Hop two:** because those rows stopped qualifying, each parent
    investment recomputes its `substantially_all_pct_direct`, and any such
    investment whose `compliance_status` is `COMPLIANT` and whose recomputed
    percentage falls below 85.00 moves to `AT_RISK` with `cure_deadline_at` set to
    the logical clock advanced by 180 days."

    Design: Difficulty/transitive_cascade/eligibility_failure_cascades_qalicb_to_qlicis_to_qeis_to_award_posture
    """
    scenario = _two_investments_funding_one_company(api)

    _fail_the_company(api, scenario)

    for investment in (scenario.qei, scenario.extras["second_qei"]):
        row = read_qei(api, investment["id"])
        assert_pct(row["substantially_all_pct_direct"], 0.00, "substantially_all_pct_direct")
        assert row["compliance_status"] == "AT_RISK"
        assert_instant(row["cure_deadline_at"], CURE_DEADLINE_FROM_FAILURE, "cure_deadline_at")
        assert row["deployment_status"] == "DEPLOYING"

    assert_cents(
        read_qei(api, scenario.qei["id"])["uninvested_cash_cents"],
        10_000_000,
        "uninvested_cash_cents",
    )


def test_two_at_risk_investments_restrict_the_award_without_freezing_it(api):
    """Hop three re-derives the award's posture from the at-risk count.

    PRD: "**Hop three:** because those investments entered `AT_RISK`, each parent
    award's `at_risk_qei_count` rises and its `compliance_posture` is re-derived,
    so an award reaching two at-risk investments moves from `UNRESTRICTED` to
    `RESTRICTED` and stops accepting new issuance."

    Design: Difficulty/transitive_cascade/eligibility_failure_cascades_qalicb_to_qlicis_to_qeis_to_award_posture
    """
    scenario = _two_investments_funding_one_company(api)

    _fail_the_company(api, scenario)

    award = read_award(api, scenario.award["id"])
    assert award["at_risk_qei_count"] == 2
    assert award["recaptured_qei_count"] == 0
    assert award["compliance_posture"] == "RESTRICTED"
    assert award["lifecycle_status"] == "ACTIVE"
    assert_pct(award["severe_distress_share_pct"], 0.00, "severe_distress_share_pct")

    assert read_cba(api, scenario.cba["id"])["status"] == "ACTIVE"


# --- From a clawback to a frozen award -------------------------------------

FIRST_YEAR_END = "2027-09-01T00:00:00.000Z"
SECOND_YEAR_END = "2028-08-31T00:00:00.000Z"
FIRST_YEAR_CURE_DEADLINE = "2028-02-28T00:00:00.000Z"
UNDERDEPLOYED_CENTS = 30_000_000


def _investment_failing_a_second_year(api):
    """An under-deployed investment that fails year one and then year two."""
    scenario = setup_at_risk_investment(
        api,
        principal_cents=UNDERDEPLOYED_CENTS,
        certification_suffix="007",
        clock=ISSUANCE_CLOCK,
    )
    set_clock(api, SECOND_YEAR_END)
    second_test = run_annual_test(api, scenario.qei, 2)
    scenario.annual_tests.append(second_test)
    return scenario


def test_a_second_failure_past_the_cure_deadline_claws_the_credit_back(api):
    """The warning year ends and the clawback lands on the next failing test.

    PRD: "A failing test against an investment *already* in `AT_RISK` whose
    `cure_deadline_at` the logical clock has passed is the end of the road: the
    investment moves to `RECAPTURED`, the test's `recapture_triggered` is set
    true, and `recapture_trigger_type` is set to `SUBSTANTIALLY_ALL_FAILURE` — or
    to `REINVESTMENT_BREACH` when the same test's `breached_obligation_count` is
    greater than 0, since returned capital left idle past its window is a
    different sin from capital that never qualified."

    PRD: "Its `window_start_at` is the investment's `issued_at` advanced by 365
    days multiplied by one less than the requested year; its `window_end_at` is
    the `issued_at` advanced by 365 days multiplied by the requested year; and
    `window_days` is always 365 under the fixed-year convention."

    Design: Difficulty/transitive_cascade/annual_test_failure_cascades_qei_recapture_to_award_freeze_to_blocked_deployment
    """
    scenario = _investment_failing_a_second_year(api)
    first_year, second_year = scenario.annual_tests[0], scenario.annual_tests[1]

    assert first_year["result"] == "FAIL"
    assert first_year["recapture_triggered"] is False

    assert_instant(second_year["window_start_at"], FIRST_YEAR_END, "window_start_at")
    assert_instant(second_year["window_end_at"], SECOND_YEAR_END, "window_end_at")
    assert second_year["window_days"] == 365
    assert_pct(second_year["measured_pct_direct"], 31.58, "measured_pct_direct")
    assert second_year["result"] == "FAIL"
    assert second_year["recapture_triggered"] is True

    qei = read_qei(api, scenario.qei["id"])
    assert qei["compliance_status"] == "RECAPTURED"
    assert qei["recapture_trigger_type"] == "SUBSTANTIALLY_ALL_FAILURE"
    assert qei["compliance_years_completed"] == 2


def test_the_exposure_reads_the_year_just_completed_and_adds_simple_interest(api):
    """Two completed years draw 1000 basis points plus 300 for each year.

    PRD: "The cumulative credit claimed after a given number of completed
    compliance years is expressed in basis points of the gross `qei_amount_cents`:
    500 after one year, 1000 after two, 1500 after three, 2100 after four, 2700
    after five, 3300 after six and 3900 after seven — the full 39 percent of the
    investment."

    PRD: "Interest is simple and never compounded, charged at 300 basis points
    per completed year on that cumulative claimed amount rather than year by
    year: the claimed amount multiplied by 300, multiplied by the number of
    completed years, divided by 10000, and rounded half-up as its own separate
    step."

    Design: Difficulty/transitive_cascade/annual_test_failure_cascades_qei_recapture_to_award_freeze_to_blocked_deployment
    """
    scenario = _investment_failing_a_second_year(api)

    qei = read_qei(api, scenario.qei["id"])
    assert_cents(qei["recapture_exposure_cents"], 10_600_000, "recapture_exposure_cents")
    assert_cents(qei["uninvested_cash_cents"], 65_000_000, "uninvested_cash_cents")


def test_the_recaptured_investment_freezes_its_award_and_blocks_the_next_placement(api):
    """A frozen posture bars deployment, not merely issuance.

    PRD: "If the allocatee's `certification_status` is `DECERTIFIED`, or the award
    has at least one investment whose `compliance_status` is `RECAPTURED`, the
    posture is `FROZEN`, which bars both new investment issuance and new
    sub-allocation deployment."

    Design: Difficulty/transitive_cascade/annual_test_failure_cascades_qei_recapture_to_award_freeze_to_blocked_deployment
    """
    scenario = _investment_failing_a_second_year(api)

    award = read_award(api, scenario.award["id"])
    assert award["compliance_posture"] == "FROZEN"
    assert award["recaptured_qei_count"] == 1
    assert award["at_risk_qei_count"] == 0
    assert award["lifecycle_status"] == "ACTIVE"

    refused = api.create_qlici(
        create_qlici_payload(
            scenario.qei["id"], scenario.qalicb["id"], principal_cents=1_000_000
        ),
        scenario.cde_headers,
    )
    validate_error(refused, ApiErrorId.ERR_AWARD_POSTURE_RESTRICTED.value, 409)

    assert_cents(
        read_qei(api, scenario.qei["id"])["uninvested_cash_cents"],
        65_000_000,
        "uninvested_cash_cents",
    )


def test_the_second_annual_test_sweeps_a_stale_certification_the_first_one_left_alone(api):
    """At exactly 365 days the certification is fresh; at 730 days it is stale.

    PRD: "It sweeps every business funded by a qualifying sub-allocation of this
    investment out of `CERTIFIED` and into `RECERTIFICATION_DUE` when that
    business's `last_certified_at` lies strictly more than 365 days before the
    logical clock, counting them in `recertification_swept_qalicb_count`."

    Design: Difficulty/transitive_cascade/annual_test_failure_cascades_qei_recapture_to_award_freeze_to_blocked_deployment
    """
    scenario = _investment_failing_a_second_year(api)

    assert scenario.annual_tests[0]["recertification_swept_qalicb_count"] == 0
    assert scenario.annual_tests[1]["recertification_swept_qalicb_count"] == 1

    company = read_qalicb(api, scenario.qalicb["id"])
    assert company["eligibility_status"] == "RECERTIFICATION_DUE"
    assert_instant(company["last_certified_at"], ISSUANCE_CLOCK, "last_certified_at")
