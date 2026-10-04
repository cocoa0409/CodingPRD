"""Buyout tests: straight-line depreciation, offset boundary, and the
depth-3 settle/withdraw/forfeit cascade."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_active_contract,
    setup_buyout_pending_contract,
    setup_finalized_period,
    create_stock_program,
    grant_award,
    set_clock,
    make_managing_partner_headers,
    TEST_USERS,
)

CONTROLLER = TEST_USERS["corporate_controller_headers"]
HR = TEST_USERS["hr_recruiter_headers"]
AUDITOR = TEST_USERS["operations_auditor_headers"]


def test_buyout_offset_at_exactly_zero_returns_full_capital(api):
    """PRD §3.4: "First, capital_return_cents is the straight-line depreciated
    buy-in: the elapsed term fraction is the number of days from
    term_start_date to departure_date — clamped so it never falls below zero
    days and never exceeds the total term length in days — divided by the
    total days from term_start_date to term_end_date; the returned capital is
    the buy_in_required_cents multiplied by the remaining (un-elapsed)
    fraction, rounded half-up to integer cents. A departure on the very first
    day returns the full buy-in; a departure on or after the term end returns
    zero, never a negative amount."
    PRD §3.4: "The offset may not exceed the sum of the capital return and the
    accrued share; an offset that does is rejected with
    ERR_OFFSET_EXCEEDS_PAYOUT, which guarantees the total payout is never
    negative."

    Design: Difficulty/boundary_precision_check/buyout_offset_at_exactly_zero_returns_full_capital
    """
    setup = setup_buyout_pending_contract(clock_at="2027-01-01T00:00:00Z")
    contract = validate_success(api.get_contract(setup["contract"]["id"], CONTROLLER))
    resp_over = api.create_buyout_order(
        contract["id"],
        {"offset_cents": 2500001, "expected_contract_version": contract["version"]},
        CONTROLLER,
    )
    validate_error(resp_over, ApiErrorId.ERR_OFFSET_EXCEEDS_PAYOUT)
    order = validate_success(
        api.create_buyout_order(
            contract["id"],
            {"offset_cents": 2500000, "expected_contract_version": contract["version"]},
            CONTROLLER,
        ),
        expected_status=201,
    )
    assert order["capital_return_cents"] == 2500000  # departure at E == 0
    assert order["accrued_share_cents"] == 0
    assert order["total_payout_cents"] == 0


def test_capital_return_depreciates_straight_line_at_mid_term(api):
    """PRD §3.4: "First, capital_return_cents is the straight-line depreciated
    buy-in: the elapsed term fraction is the number of days from
    term_start_date to departure_date — clamped so it never falls below zero
    days and never exceeds the total term length in days — divided by the
    total days from term_start_date to term_end_date; the returned capital is
    the buy_in_required_cents multiplied by the remaining (un-elapsed)
    fraction, rounded half-up to integer cents."
    PRD §3.4: "Third, total_payout_cents is the capital return plus the
    accrued share minus the offset."

    Design: Corner/calculations/capital_return_depreciates_straight_line_at_mid_term
    """
    setup = setup_active_contract(term_start_date="2029-01-01", term_end_date="2031-01-01")
    set_clock("2030-01-01T00:00:00Z")
    validate_success(
        api.depart_contract(
            setup["contract"]["id"],
            make_managing_partner_headers(setup["partner"]["id"]),
        )
    )
    contract = validate_success(api.get_contract(setup["contract"]["id"], CONTROLLER))
    order = validate_success(
        api.create_buyout_order(
            contract["id"],
            {"offset_cents": 0, "expected_contract_version": contract["version"]},
            CONTROLLER,
        ),
        expected_status=201,
    )
    # Term [2029-01-01, 2031-01-01) = 730 days (no intervening leap day);
    # departure 2030-01-01 -> E = 365, so the remaining fraction is exactly 1/2.
    assert order["capital_return_cents"] == 1250000
    assert order["accrued_share_cents"] == 0
    assert order["total_payout_cents"] == 1250000
    assert order["status"] == "DRAFT"


def test_buyout_offset_at_exactly_payout_succeeds(api):
    """PRD §3.4: "The offset may not exceed the sum of the capital return and
    the accrued share; an offset that does is rejected with
    ERR_OFFSET_EXCEEDS_PAYOUT, which guarantees the total payout is never
    negative."
    PRD §3.4: "A departure on the very first day returns the full buy-in; a
    departure on or after the term end returns zero, never a negative amount."

    Design: Difficulty/boundary_precision_check/buyout_offset_at_exactly_zero_returns_full_capital
    """
    setup = setup_buyout_pending_contract(clock_at="2027-01-01T00:00:00Z")
    contract = validate_success(api.get_contract(setup["contract"]["id"], CONTROLLER))
    order = validate_success(
        api.create_buyout_order(
            contract["id"],
            {"offset_cents": 2500000, "expected_contract_version": contract["version"]},
            CONTROLLER,
        ),
        expected_status=201,
    )
    assert order["capital_return_cents"] == 2500000
    assert order["accrued_share_cents"] == 0
    assert order["total_payout_cents"] == 0


def test_buyout_accrued_share_and_valuation_conservation(api):
    """PRD §3.4: "Second, accrued_share_cents is the sum of
    partner_share_cents over the contract's restaurant's profit periods that
    are FINALIZED or LOCKED, have partner_share_paid false, and have a
    period_end_date on or before the departure_date."
    PRD §3.4: "Third, total_payout_cents is the capital return plus the
    accrued share minus the offset."
    PRD §3.4: "The conservation invariant holds by construction: capital
    return plus accrued share always equals total payout plus offset."

    Design: Difficulty/transitive_cascade/buyout_pay_cascades_settlement_withdrawal_and_grant_forfeiture
    """
    setup = setup_finalized_period(
        line_items=[("REVENUE", 8000000), ("LABOR", 2000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    # Finalized share: 8% of 5000000 + 10% of 1000000 == 500000, unpaid.
    set_clock("2028-06-01T00:00:00Z")
    validate_success(
        api.depart_contract(
            setup["contract"]["id"],
            make_managing_partner_headers(setup["partner"]["id"]),
        )
    )
    contract = validate_success(api.get_contract(setup["contract"]["id"], CONTROLLER))
    order = validate_success(
        api.create_buyout_order(
            contract["id"],
            {"offset_cents": 0, "expected_contract_version": contract["version"]},
            CONTROLLER,
        ),
        expected_status=201,
    )
    assert order["accrued_share_cents"] == 500000
    assert (
        order["capital_return_cents"] + order["accrued_share_cents"]
        == order["total_payout_cents"] + order["offset_cents"]
    )
    validate_success(api.approve_buyout_order(order["id"], CONTROLLER))
    paid = validate_success(api.pay_buyout_order(order["id"], CONTROLLER))
    assert paid["status"] == "PAID"
    contract_now = validate_success(api.get_contract(setup["contract"]["id"], CONTROLLER))
    assert contract_now["status"] == "SETTLED"
    period_now = validate_success(api.get_profit_period(setup["period"]["id"], AUDITOR))
    assert period_now["partner_share_paid"] is True


def test_buyout_pay_cascades_settlement_withdrawal_and_grant_forfeiture(api):
    """PRD §3.4: "Payment moves it from APPROVED to PAID and fires the depth-3
    cascade: the contract moves from BUYOUT_PENDING to SETTLED, its
    capital_account_cents returns to 0, the partner moves from PLACED to
    WITHDRAWN — cascading award forfeiture per §3.7 — and every profit period
    whose accrued share was swept into the order has its partner_share_paid
    set to true, so a period's share can never be paid out twice."
    PRD §3.10: "when a partner moves to WITHDRAWN — by recruiter withdrawal,
    by a settled buyout, or by a lapsed funding window — every grant that
    partner holds in EARNED or VESTING moves to FORFEITED, and each forfeiture
    credits the grant's units_awarded back to its program's units_reserved."

    Design: Difficulty/transitive_cascade/buyout_pay_cascades_settlement_withdrawal_and_grant_forfeiture
    """
    setup = setup_finalized_period(
        line_items=[("REVENUE", 8000000), ("LABOR", 2000000)],
        clock_at="2027-04-15T00:00:00Z",
    )
    # The forfeiture cascade is program-agnostic; a CONFERENCE grant (zero
    # units, eligibility satisfied by this period's 70.00 score under the
    # explicitly-set threshold) exercises the cascade identically.
    program = create_stock_program(
        stock_units_pool=1000,
        eligibility_threshold_score=70,
        program_type="CONFERENCE",
    )
    grant = grant_award(program["id"], setup["partner"]["id"], setup["period"]["id"])
    assert grant["status"] == "EARNED"
    validate_success(api.vest_award_grant(grant["id"], CONTROLLER))

    # Depart ~2 months after the grant so the grant is still VESTING at
    # withdrawal time — a VESTED grant would survive withdrawal (§3.10).
    set_clock("2027-06-01T00:00:00Z")
    validate_success(
        api.depart_contract(
            setup["contract"]["id"],
            make_managing_partner_headers(setup["partner"]["id"]),
        )
    )
    contract = validate_success(api.get_contract(setup["contract"]["id"], CONTROLLER))
    order = validate_success(
        api.create_buyout_order(
            contract["id"],
            {"offset_cents": 0, "expected_contract_version": contract["version"]},
            CONTROLLER,
        ),
        expected_status=201,
    )
    validate_success(api.approve_buyout_order(order["id"], CONTROLLER))
    paid = validate_success(api.pay_buyout_order(order["id"], CONTROLLER))
    assert paid["status"] == "PAID"

    contract_now = validate_success(api.get_contract(setup["contract"]["id"], CONTROLLER))
    assert contract_now["status"] == "SETTLED"
    assert contract_now["capital_account_cents"] == 0
    partner_now = validate_success(api.get_partner(setup["partner"]["id"], HR))
    assert partner_now["status"] == "WITHDRAWN"
    grant_now = validate_success(api.get_award_grant(grant["id"], CONTROLLER))
    assert grant_now["status"] == "FORFEITED"
    program_now = validate_success(api.get_award_program(program["id"], CONTROLLER))
    assert program_now["units_reserved"] == 0
    period_now = validate_success(api.get_profit_period(setup["period"]["id"], AUDITOR))
    assert period_now["partner_share_paid"] is True
