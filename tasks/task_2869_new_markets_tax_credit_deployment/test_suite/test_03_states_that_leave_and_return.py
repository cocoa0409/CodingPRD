"""State machines that are not one-way streets.

A project company's eligibility can be lost and won back, and an investment
carries two state dimensions that advance on their own schedules.
"""
from test_helpers import (
    assert_instant,
    assert_cents,
    assert_pct,
    create_qalicb,
    create_tract,
    make_agency_headers,
    open_obligation_of,
    read_obligation,
    read_qalicb,
    read_qei,
    read_qlici,
    reinvest,
    repay_principal,
    run_eligibility_test,
    set_clock,
    setup_deployed_investment,
    validate_paginated,
)

FIRST_PASS_CLOCK = "2026-09-01T00:00:00.000Z"
FAILURE_CLOCK = "2026-10-01T00:00:00.000Z"
SECOND_PASS_CLOCK = "2026-11-01T00:00:00.000Z"

#: A submission that misses the gross-income floor and breaks the collectibles cap.
FAILING_PRONGS = {"gross_income_lic_pct": 48.00, "collectibles_pct": 6.00}
#: A thinner but sufficient submission: 55.00 clears 50.00 and 2.00 is under 5.00.
RECOVERY_PRONGS = {"gross_income_lic_pct": 55.00, "collectibles_pct": 2.00}


def _company_tested_three_times(api):
    """Register a business in a severe tract, then pass, fail and pass again."""
    set_clock(api, FIRST_PASS_CLOCK)
    tract = create_tract(api)
    qalicb = create_qalicb(api, tract)
    first = run_eligibility_test(api, qalicb)

    set_clock(api, FAILURE_CLOCK)
    second = run_eligibility_test(api, qalicb, **FAILING_PRONGS)

    set_clock(api, SECOND_PASS_CLOCK)
    third = run_eligibility_test(api, qalicb, **RECOVERY_PRONGS)
    return qalicb, [first, second, third]


def test_a_single_failure_lands_the_company_in_failed_rather_than_disqualified(api):
    """One failed prong set is a warning, not a permanent bar.

    PRD: "A failure raises `consecutive_failed_test_count` by 1 and sets
    `latest_test_result` to `FAIL`; if the raised counter is still below 2 the
    business lands in `FAILED`, and once the raised counter reaches 2 the
    business lands in `DISQUALIFIED`."

    Design: Difficulty/non_linear_state_machine/qalicb_eligibility_status_cycles_pending_certified_failed_certified
    """
    set_clock(api, FIRST_PASS_CLOCK)
    tract = create_tract(api)
    qalicb = create_qalicb(api, tract)
    run_eligibility_test(api, qalicb)

    set_clock(api, FAILURE_CLOCK)
    failed = run_eligibility_test(api, qalicb, **FAILING_PRONGS)
    assert failed["result"] == "FAIL"

    company = read_qalicb(api, qalicb["id"])
    assert company["eligibility_status"] == "FAILED"
    assert company["consecutive_failed_test_count"] == 1
    assert company["latest_test_result"] == "FAIL"
    assert_instant(company["last_certified_at"], FIRST_PASS_CLOCK, "last_certified_at")


def test_a_later_passing_test_recertifies_the_company_and_clears_its_failure_count(api):
    """The cycle closes: pending to certified to failed and back to certified.

    PRD: "From `PENDING`, from `RECERTIFICATION_DUE`, from `FAILED`, or from
    `CERTIFIED` itself, a passing test lands the business in `CERTIFIED`, sets
    `last_certified_at` to the logical clock, sets `latest_test_result` to
    `PASS`, resets `consecutive_failed_test_count` to 0, and increments the
    business's `version`."

    Design: Difficulty/non_linear_state_machine/qalicb_eligibility_status_cycles_pending_certified_failed_certified
    """
    qalicb, tests = _company_tested_three_times(api)

    assert tests[2]["result"] == "PASS"

    company = read_qalicb(api, qalicb["id"])
    assert company["eligibility_status"] == "CERTIFIED"
    assert company["consecutive_failed_test_count"] == 0
    assert company["latest_test_result"] == "PASS"
    assert_instant(company["last_certified_at"], SECOND_PASS_CLOCK, "last_certified_at")


def test_failed_prongs_are_named_in_the_fixed_order_and_every_test_row_is_kept(api):
    """Only the percentages on each request decide that request's failed prongs.

    PRD: "The `failed_prongs` array names every prong that failed, always in the
    fixed order `LOCATION`, `GROSS_INCOME`, `SERVICES`, `TANGIBLE_PROPERTY`,
    `COLLECTIBLES`, `NQFP`, whatever order the inputs arrived in, and it is an
    empty array on a pass."

    Design: Difficulty/non_linear_state_machine/qalicb_eligibility_status_cycles_pending_certified_failed_certified
    """
    qalicb, tests = _company_tested_three_times(api)

    assert tests[0]["failed_prongs"] == []
    assert tests[1]["failed_prongs"] == ["GROSS_INCOME", "COLLECTIBLES"]
    assert tests[2]["failed_prongs"] == []

    rows, meta = validate_paginated(
        api.list_eligibility_tests(qalicb["id"], make_agency_headers())
    )
    assert meta["total_count"] == 3
    assert [row["result"] for row in rows] == ["PASS", "FAIL", "PASS"]


# --- The two dimensions of one investment ----------------------------------

REPAYMENT_CLOCK = "2026-12-01T00:00:00.000Z"
REDEPLOYMENT_CLOCK = "2026-12-15T00:00:00.000Z"
CURE_DEADLINE = "2027-05-30T00:00:00.000Z"
REDEPLOY_BY = "2027-12-01T00:00:00.000Z"
RETURNED_CENTS = 50_000_000


def _investment_with_half_its_principal_back(api):
    scenario = setup_deployed_investment(
        api, clock=FIRST_PASS_CLOCK, certification_suffix="005"
    )
    set_clock(api, REPAYMENT_CLOCK)
    repay_principal(api, scenario.cde, scenario.qlici, RETURNED_CENTS)
    return scenario


def test_returned_principal_moves_the_cash_dimension_and_the_compliance_dimension_apart(api):
    """One repayment leaves the investment redeploying its cash and at risk on its testing.

    PRD: "A qualified equity investment has a `deployment_status` that tracks
    where its cash sits and a `compliance_status` that tracks how its testing has
    gone; the two evolve independently and reach terminal values independently."

    Design: Difficulty/non_linear_state_machine/qei_deployment_and_compliance_dimensions_advance_independently
    """
    scenario = _investment_with_half_its_principal_back(api)

    placement = read_qlici(api, scenario.qlici["id"])
    assert placement["status"] == "PARTIALLY_REPAID"
    assert_cents(placement["outstanding_principal_cents"], 35_000_000, "outstanding_principal_cents")
    assert_cents(placement["total_repaid_cents"], RETURNED_CENTS, "total_repaid_cents")

    qei = read_qei(api, scenario.qei["id"])
    assert qei["deployment_status"] == "REINVESTMENT_PENDING"
    assert qei["compliance_status"] == "AT_RISK"
    assert_pct(qei["substantially_all_pct_direct"], 36.84, "substantially_all_pct_direct")
    assert_cents(qei["uninvested_cash_cents"], 60_000_000, "uninvested_cash_cents")
    assert_instant(qei["cure_deadline_at"], CURE_DEADLINE, "cure_deadline_at")


def test_the_obligation_records_the_returned_amount_and_a_365_day_redeployment_deadline(api):
    """Repayment restarts the duty rather than ending it.

    PRD: "**Hop two** returns the cash and opens the redeployment duty: the
    investment's `uninvested_cash_cents` rises by the repaid amount, and a
    reinvestment obligation row is created naming the investment through `qei_id`
    and the repaid sub-allocation through `source_qlici_id`, with `amount_cents`
    equal to the principal just returned, `reinvested_cents` at 0, `arose_at`
    stamped from the logical clock, `reinvest_by_at` set to that instant advanced
    by 365 days, `status` `OPEN`, and `satisfied_at` and `breached_at` both null."

    Design: Difficulty/non_linear_state_machine/qei_deployment_and_compliance_dimensions_advance_independently
    """
    scenario = _investment_with_half_its_principal_back(api)

    obligation = open_obligation_of(api, scenario.qei["id"])
    assert obligation["source_qlici_id"] == scenario.qlici["id"]
    assert_cents(obligation["amount_cents"], RETURNED_CENTS, "amount_cents")
    assert_cents(obligation["reinvested_cents"], 0, "reinvested_cents")
    assert_instant(obligation["arose_at"], REPAYMENT_CLOCK, "arose_at")
    assert_instant(obligation["reinvest_by_at"], REDEPLOY_BY, "reinvest_by_at")
    assert obligation["status"] == "OPEN"
    assert obligation["satisfied_at"] is None
    assert obligation["breached_at"] is None


def test_redeploying_the_same_capital_satisfies_the_obligation_and_restores_compliance(api):
    """The cash dimension steps back to deploying while the compliance dimension heals.

    PRD: "On success the obligation's `reinvested_cents` rises by the amount, the
    target sub-allocation's `principal_cents` *and* its
    `outstanding_principal_cents` both rise by the same amount, and the
    investment's `uninvested_cash_cents` falls by it."

    PRD: "Once no obligation on the investment remains `OPEN`, the investment
    leaves `REINVESTMENT_PENDING`: it returns to `DEPLOYING` when uninvested cash
    remains greater than 0 after the reinvestment, and moves to `FULLY_DEPLOYED`
    when the reinvestment brought `uninvested_cash_cents` to exactly 0."

    Design: Difficulty/non_linear_state_machine/qei_deployment_and_compliance_dimensions_advance_independently
    """
    scenario = _investment_with_half_its_principal_back(api)
    obligation = open_obligation_of(api, scenario.qei["id"])

    set_clock(api, REDEPLOYMENT_CLOCK)
    reinvest(api, scenario.cde, obligation, scenario.qlici, RETURNED_CENTS)

    settled = read_obligation(api, obligation["id"])
    assert settled["status"] == "SATISFIED"
    assert_cents(settled["reinvested_cents"], RETURNED_CENTS, "reinvested_cents")
    assert_instant(settled["satisfied_at"], REDEPLOYMENT_CLOCK, "satisfied_at")

    placement = read_qlici(api, scenario.qlici["id"])
    assert_cents(placement["principal_cents"], 135_000_000, "principal_cents")
    assert_cents(placement["outstanding_principal_cents"], 85_000_000, "outstanding_principal_cents")
    assert placement["status"] == "PARTIALLY_REPAID"

    qei = read_qei(api, scenario.qei["id"])
    assert qei["deployment_status"] == "DEPLOYING"
    assert_cents(qei["uninvested_cash_cents"], 10_000_000, "uninvested_cash_cents")
    assert qei["compliance_status"] == "COMPLIANT"
    assert_pct(qei["substantially_all_pct_direct"], 89.47, "substantially_all_pct_direct")
    assert qei["cure_deadline_at"] is None
