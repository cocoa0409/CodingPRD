"""Operations refused because of a state that lives on a different row.

A placement is blocked by a project company that an annual test quietly swept out
of certification, and an unwind is blocked by a counter on the investment.
"""
from test_helpers import (
    ApiErrorId,
    INVESTOR_DELTA_USER_ID,
    advance_compliance_years,
    assert_cents,
    assert_instant,
    assert_pct,
    create_cba,
    create_qlici_payload,
    issue_qei,
    deploy_qlici,
    make_agency_headers,
    open_unwind,
    open_unwind_payload,
    option_window_open,
    read_award,
    read_qalicb,
    read_qei,
    read_qlici,
    run_annual_test,
    set_clock,
    setup_active_award,
    setup_certified_project_company,
    setup_deployed_investment,
    setup_funded_fund,
    validate_error,
    validate_paginated,
)

CERTIFICATION_CLOCK = "2026-08-01T00:00:00.000Z"
ISSUANCE_CLOCK = "2026-09-01T00:00:00.000Z"
TEST_CLOCK = "2027-08-15T00:00:00.000Z"


def _investment_whose_company_goes_stale_mid_window(api):
    """The business was certified a month before the money moved, and never again."""
    scenario = setup_active_award(
        api, clock=CERTIFICATION_CLOCK, certification_suffix="012"
    )
    setup_certified_project_company(api, scenario)
    scenario.cba = create_cba(api, scenario.cde, scenario.qalicb, scenario.award)

    set_clock(api, ISSUANCE_CLOCK)
    setup_funded_fund(api, scenario)
    scenario.award = read_award(api, scenario.award["id"])
    scenario.qei = issue_qei(api, scenario.cde, scenario.award, scenario.fund)
    scenario.qlici = deploy_qlici(
        api, scenario.cde, scenario.qei, scenario.qalicb
    )
    scenario.qlicis.append(scenario.qlici)

    set_clock(api, TEST_CLOCK)
    return scenario


def test_a_passing_annual_test_still_sweeps_a_certification_older_than_365_days(api):
    """The investment passes and the business it funds loses its certification anyway.

    PRD: "It sweeps every business funded by a qualifying sub-allocation of this
    investment out of `CERTIFIED` and into `RECERTIFICATION_DUE` when that
    business's `last_certified_at` lies strictly more than 365 days before the
    logical clock, counting them in `recertification_swept_qalicb_count`."

    Design: Difficulty/cross_entity_state_dependency/qlici_deployment_blocked_by_the_qalicb_state_a_sibling_qei_annual_test_swept
    """
    scenario = _investment_whose_company_goes_stale_mid_window(api)

    before = read_qalicb(api, scenario.qalicb["id"])
    assert before["eligibility_status"] == "CERTIFIED"
    assert_instant(before["last_certified_at"], CERTIFICATION_CLOCK, "last_certified_at")

    test = run_annual_test(api, scenario.qei, 1)
    assert test["result"] == "PASS"
    assert_pct(test["measured_pct_direct"], 89.47, "measured_pct_direct")
    assert test["recertification_swept_qalicb_count"] == 1

    after = read_qalicb(api, scenario.qalicb["id"])
    assert after["eligibility_status"] == "RECERTIFICATION_DUE"
    assert_instant(after["last_certified_at"], CERTIFICATION_CLOCK, "last_certified_at")


def test_the_swept_company_keeps_its_capital_but_takes_no_new_placement(api):
    """Outstanding principal still qualifies while the door closes on new money.

    PRD: "While a business sits in `RECERTIFICATION_DUE`, principal already
    outstanding keeps qualifying, but no new sub-allocation may be deployed to it —
    that attempt is `ERR_QALICB_NOT_CERTIFIED`, exactly as for a business still in
    `PENDING` or one in `FAILED`."

    Design: Difficulty/cross_entity_state_dependency/qlici_deployment_blocked_by_the_qalicb_state_a_sibling_qei_annual_test_swept
    """
    scenario = _investment_whose_company_goes_stale_mid_window(api)
    run_annual_test(api, scenario.qei, 1)

    refused = api.create_qlici(
        create_qlici_payload(
            scenario.qei["id"],
            scenario.qalicb["id"],
            loan_class="B",
            principal_cents=5_000_000,
        ),
        scenario.cde_headers,
    )
    validate_error(refused, ApiErrorId.ERR_QALICB_NOT_CERTIFIED.value, 422)

    placement = read_qlici(api, scenario.qlici["id"])
    assert placement["status"] == "DEPLOYED"
    assert_cents(
        placement["outstanding_principal_cents"], 85_000_000, "outstanding_principal_cents"
    )

    qei = read_qei(api, scenario.qei["id"])
    assert_cents(qei["uninvested_cash_cents"], 10_000_000, "uninvested_cash_cents")
    assert qei["deployment_status"] == "DEPLOYING"
    assert qei["compliance_status"] == "COMPLIANT"

    assert read_qalicb(api, scenario.qalicb["id"])["funding_qlici_count"] == 1


# --- The unwind waits on a counter -----------------------------------------

YEAR_SEVEN_START = "2032-08-30T00:00:00.000Z"
OPTION_WINDOW_OPENS = "2033-08-30T00:00:00.000Z"
OPTION_WINDOW_CLOSES = "2033-11-28T00:00:00.000Z"


def _investment_six_years_in_at_the_option_window(api):
    scenario = setup_deployed_investment(
        api, clock=ISSUANCE_CLOCK, certification_suffix="013"
    )
    advance_compliance_years(api, scenario, 6)
    set_clock(api, option_window_open(scenario.qei["issued_at"]))
    return scenario


def _attempt_unwind(api, scenario):
    return api.open_unwind_transaction(
        scenario.qei["id"],
        open_unwind_payload(scenario.cde["id"]),
        scenario.cde_headers,
    )


def test_the_option_window_cannot_open_until_the_seventh_year_is_recorded(api):
    """Six completed years and the right instant are not enough.

    PRD: "The investment must have `compliance_years_completed` equal to 7, or the
    request is refused with `ERR_COMPLIANCE_PERIOD_NOT_COMPLETE`, and it must have
    no live unwind row: an existing row in `OPTION_WINDOW_OPEN`, `PUT_EXERCISED`,
    `CALL_EXERCISED` or `SETTLED` blocks a new one with `ERR_UNWIND_ALREADY_OPEN`,
    and only a prior row in `EXPIRED` permits a fresh attempt."

    Design: Difficulty/cross_entity_state_dependency/unwind_opening_gated_on_the_qei_compliance_year_counter_reaching_seven
    """
    scenario = _investment_six_years_in_at_the_option_window(api)

    qei = read_qei(api, scenario.qei["id"])
    assert qei["compliance_years_completed"] == 6
    assert qei["compliance_status"] == "COMPLIANT"

    refused = _attempt_unwind(api, scenario)
    validate_error(refused, ApiErrorId.ERR_COMPLIANCE_PERIOD_NOT_COMPLETE.value, 422)

    _rows, meta = validate_paginated(
        api.list_unwind_transactions(scenario.qei["id"], make_agency_headers())
    )
    assert meta["total_count"] == 0


def test_the_seventh_test_lets_the_window_open_and_price_both_options(api):
    """The residual reaches back into the fund's leverage balance to price the call.

    PRD: "The `fund_residual_value_cents` is the investment's
    `uninvested_cash_cents`, plus the sum of `outstanding_principal_cents` across
    its sub-allocations whose `status` is `DEPLOYED`, `PARTIALLY_REPAID` or
    `NON_QUALIFYING`, less the fund's `leverage_loan_outstanding_cents`."

    PRD: "The `call_price_cents` is fair-market: take the residual value floored at
    zero, multiply by 250 basis points, divide by 10000 and round half-up; then
    subtract the investment's `accrued_unpaid_fee_cents`; then apply a floor of
    100000 cents to whatever remains."

    PRD: "The `option_window_open_at` is the investment's `issued_at` advanced by
    2555 days — seven years of 365 days each — and the `option_window_close_at` is
    90 days after that, so the window's lower bound is inclusive and its upper
    bound exclusive."

    Design: Difficulty/cross_entity_state_dependency/unwind_opening_gated_on_the_qei_compliance_year_counter_reaching_seven
    """
    scenario = _investment_six_years_in_at_the_option_window(api)
    _attempt_unwind(api, scenario)

    seventh = run_annual_test(api, scenario.qei, 7)
    assert seventh["result"] == "PASS"
    assert_instant(seventh["window_start_at"], YEAR_SEVEN_START, "window_start_at")
    assert_instant(seventh["window_end_at"], OPTION_WINDOW_OPENS, "window_end_at")
    assert read_qei(api, scenario.qei["id"])["compliance_years_completed"] == 7

    unwind = open_unwind(api, scenario.cde, scenario.qei, scenario.cde["id"])
    assert unwind["status"] == "OPTION_WINDOW_OPEN"
    assert_instant(unwind["option_window_open_at"], OPTION_WINDOW_OPENS, "option_window_open_at")
    assert_instant(unwind["option_window_close_at"], OPTION_WINDOW_CLOSES, "option_window_close_at")
    assert_cents(unwind["fund_residual_value_cents"], 60_000_000, "fund_residual_value_cents")
    assert_cents(unwind["put_price_cents"], 100_000, "put_price_cents")
    assert_cents(unwind["call_price_cents"], 1_500_000, "call_price_cents")


def test_the_put_holder_is_taken_from_the_fund_and_the_call_holder_from_the_request(api):
    """Only the investor that capitalised the fund can hold the put.

    PRD: "The put holder is never taken from the body: `put_holder_user_id` is
    copied from the `investor_user_id` of the investment's fund, and that identity
    alone may exercise the put."

    Design: Difficulty/cross_entity_state_dependency/unwind_opening_gated_on_the_qei_compliance_year_counter_reaching_seven
    """
    scenario = _investment_six_years_in_at_the_option_window(api)
    run_annual_test(api, scenario.qei, 7)

    unwind = open_unwind(api, scenario.cde, scenario.qei, scenario.cde["id"])

    assert unwind["put_holder_user_id"] == INVESTOR_DELTA_USER_ID
    assert unwind["call_holder_user_id"] == scenario.cde["id"]
    assert unwind["exercised_option_type"] is None
    assert unwind["exercised_at"] is None
    assert_cents(unwind["settlement_amount_cents"], 0, "settlement_amount_cents")

    assert read_qalicb(api, scenario.qalicb["id"])["eligibility_status"] == "RECERTIFICATION_DUE"
