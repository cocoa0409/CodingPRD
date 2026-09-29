"""Settling a repossession sale: commission tiers, cost classes and the exact
zero-gap boundary between deficiency and surplus (PRD §3.9).

The same recovery walk is finalized at two different contract prices: one that
leaves 565495 cents over and one that lands on the payoff figure to the cent.
"""

from test_helpers import (
    assert_obligation_buckets_zeroed,
    fixtures,
    validate_success,
)

FUND_CLOCK = "2026-08-01T00:00:00Z"
FIRST_DUE_DATE = "2026-09-01T00:00:00Z"
ESCROW_TARGET_CENTS = 200000
FIRST_ASSESSMENT_CLOCK = "2026-11-01T00:00:00Z"
SECOND_ASSESSMENT_CLOCK = "2026-11-12T00:00:00Z"
POSSESSION_CLOCK = "2026-11-22T00:00:00Z"

PRINCIPAL_CENTS = 4600000
INTEREST_AT_DEFAULT_CENTS = 165505
LATE_FEE_CENTS = 3500
REPOSSESSION_EXPENSE_SEED_CENTS = 185000

# ─── The surplus settlement ───
CAPITALIZED_LINE = {
    "category": "FLOORING",
    "cost_cents": 205000,
    "cost_class": "CAPITALIZED",
}
EXPENSED_LINE = {
    "category": "TRANSPORT_AND_SETUP",
    "cost_cents": 40000,
    "cost_class": "EXPENSED",
}
SURPLUS_ASKING_PRICE_CENTS = 6250000
SURPLUS_RESALE_PRICE_CENTS = 6100000
SURPLUS_COMMISSION_BPS = 550
SURPLUS_COMMISSION_CENTS = 335500
SURPLUS_REFURBISHMENT_COST_CENTS = 205000
SURPLUS_RECOVERY_EXPENSE_CENTS = 225000
SURPLUS_NET_PROCEEDS_CENTS = 5559500
SURPLUS_PAYOFF_CENTS = 4994005
SURPLUS_CENTS = 565495

# ─── The exact settlement ───
SETTLED_ASKING_PRICE_CENTS = 5400000
SETTLED_RESALE_PRICE_CENTS = 5326887
SETTLED_COMMISSION_BPS = 700
SETTLED_COMMISSION_CENTS = 372882
SETTLED_NET_PROCEEDS_CENTS = 4954005
SETTLED_PAYOFF_CENTS = 4954005


def _case_in_remarketing(api, asking_price_cents, refurbishment_lines=()):
    """A repossession case walked to REMARKETING on a funded community loan."""
    scenario = fixtures.setup_funded_community_loan(
        api,
        clock=FUND_CLOCK,
        first_due_date=FIRST_DUE_DATE,
        escrow_target_cents=ESCROW_TARGET_CENTS,
    )
    loan_id = scenario["loan"]["id"]
    for clock in (FIRST_ASSESSMENT_CLOCK, SECOND_ASSESSMENT_CLOCK):
        fixtures.set_clock(api, clock)
        scenario["loan"] = fixtures.run_servicing_assessment(api, loan_id)

    case = validate_success(api.declare_default(loan_id, fixtures.RECOVERY), 201)
    case = fixtures.issue_notice(api, case["id"], "RTC-2026-0455")
    fixtures.set_clock(api, POSSESSION_CLOCK)
    case = fixtures.obtain_possession(api, case["id"])

    recovery_valuation = fixtures.create_certified_valuation(
        api,
        scenario["unit"]["id"],
        scenario["guide"]["id"],
        "RECOVERY_LIQUIDATION",
    )
    case = fixtures.begin_refurbishment(api, case["id"], recovery_valuation["id"])
    for line in refurbishment_lines:
        case = fixtures.record_refurbishment_cost(
            api, case["id"], line["category"], line["cost_cents"], line["cost_class"]
        )
    scenario["case"] = fixtures.list_for_resale(api, case["id"], asking_price_cents)
    scenario["recovery_valuation"] = recovery_valuation
    scenario["loan"] = fixtures.read_loan(api, loan_id)
    return scenario


def test_commission_tier_is_selected_from_gross_proceeds_before_commission(api):
    """PRD §3.9: "Commission is tiered off gross proceeds — never off net
    proceeds, never off the asking price, and never off the liquidation
    valuation."
    PRD §3.9: "The tier is 700 basis points when `gross_proceeds_cents` is
    3,000,000 cents or less, 550 basis points when it is above that but 6,000,000
    cents or less, and 400 basis points above 6,000,000 cents."
    PRD §3.9: "To that tier is added the community's `sales_commission_bps` when,
    and only when, the unit's `placement_type` is `COMMUNITY` and that
    community's `operator_agreement_status` is `EXECUTED` — the operator earns
    its referral fee only where it has a live agreement."

    Design: Difficulty/combinatorial_formula/deficiency_settlement_commission_tier_keyed_on_gross_proceeds
    """
    scenario = _case_in_remarketing(
        api, SURPLUS_ASKING_PRICE_CENTS, (CAPITALIZED_LINE, EXPENSED_LINE)
    )

    case = fixtures.finalize_sale(
        api, scenario["case"]["id"], SURPLUS_RESALE_PRICE_CENTS
    )

    assert case["gross_proceeds_cents"] == SURPLUS_RESALE_PRICE_CENTS
    assert case["commission_bps"] == SURPLUS_COMMISSION_BPS, (
        "6100000 cents is above 6000000, so the 400 bps tier applies, and the "
        "executed community agreement adds its own 150 bps"
    )
    assert case["commission_cents"] == SURPLUS_COMMISSION_CENTS
    assert case["net_proceeds_cents"] == SURPLUS_NET_PROCEEDS_CENTS


def test_capitalized_line_cuts_net_proceeds_while_expensed_line_raises_payoff(api):
    """PRD §3.9: "A `CAPITALIZED` line adds its `cost_cents` to the case's
    `refurbishment_cost_cents`, which will later be deducted from sale proceeds.
    An `EXPENSED` line instead adds its `cost_cents` immediately to the case's
    `recovery_expense_cents`, which raises the amount the collateral has to cover
    rather than reducing what it fetched."
    PRD §3.9: "What the collateral had to cover is `payoff_amount_cents`,
    computed as the loan's `principal_balance_cents` plus
    `interest_accrued_unpaid_cents` plus `fees_outstanding_cents` plus
    `force_placed_premium_outstanding_cents` plus the case's
    `recovery_expense_cents`, less the loan's `escrow_balance_cents`."

    Design: Difficulty/combinatorial_formula/deficiency_settlement_commission_tier_keyed_on_gross_proceeds
    """
    scenario = _case_in_remarketing(
        api, SURPLUS_ASKING_PRICE_CENTS, (CAPITALIZED_LINE, EXPENSED_LINE)
    )
    loan_before = scenario["loan"]
    assert loan_before["interest_accrued_unpaid_cents"] == INTEREST_AT_DEFAULT_CENTS
    assert loan_before["fees_outstanding_cents"] == LATE_FEE_CENTS
    assert loan_before["escrow_balance_cents"] == 0
    assert scenario["case"]["refurbishment_cost_cents"] == (
        SURPLUS_REFURBISHMENT_COST_CENTS
    )
    assert scenario["case"]["recovery_expense_cents"] == SURPLUS_RECOVERY_EXPENSE_CENTS

    case = fixtures.finalize_sale(
        api, scenario["case"]["id"], SURPLUS_RESALE_PRICE_CENTS
    )

    assert case["refurbishment_cost_cents"] == SURPLUS_REFURBISHMENT_COST_CENTS, (
        "only the capitalized line is deducted from proceeds"
    )
    assert case["recovery_expense_cents"] == SURPLUS_RECOVERY_EXPENSE_CENTS, (
        "the 185000-cent repossession seed plus the 40000-cent expensed line"
    )
    assert case["payoff_amount_cents"] == SURPLUS_PAYOFF_CENTS
    assert case["net_proceeds_cents"] == SURPLUS_NET_PROCEEDS_CENTS
    assert case["surplus_cents"] == SURPLUS_CENTS
    assert case["deficiency_balance_cents"] == 0


def test_surplus_closes_the_case_and_releases_the_collateral(api):
    """PRD §3.9: "When `surplus_cents` is greater than zero, the case closes at
    `CLOSED_SURPLUS`, the loan moves from `RECOVERY` to `PAID_OFF`, and the
    surplus is recorded as owed back to the borrower for remittance."
    PRD §3.9: "In every one of the three arms, all four obligation buckets on the
    loan — `principal_balance_cents`, `interest_accrued_unpaid_cents`,
    `fees_outstanding_cents` and `force_placed_premium_outstanding_cents` — are
    zeroed, the unit's `recovery_hold` is cleared to false and its `title_status`
    returns to `ACTIVE_TITLE`, the recorded filing moves to `RELEASED` and the
    loan's lien dimension moves to `RELEASED`, the borrower's
    `units_under_recovery_hold_count` falls by one with `status` returning to
    `ACTIVE` at zero, and the loan's `version` increments."

    Design: Difficulty/combinatorial_formula/deficiency_settlement_commission_tier_keyed_on_gross_proceeds
    """
    scenario = _case_in_remarketing(
        api, SURPLUS_ASKING_PRICE_CENTS, (CAPITALIZED_LINE, EXPENSED_LINE)
    )

    case = fixtures.finalize_sale(
        api, scenario["case"]["id"], SURPLUS_RESALE_PRICE_CENTS
    )
    assert case["status"] == "CLOSED_SURPLUS"

    loan = fixtures.read_loan(api, scenario["loan"]["id"])
    assert loan["servicing_state"] == "PAID_OFF"
    assert loan["perfection_state"] == "RELEASED"
    assert_obligation_buckets_zeroed(loan)

    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    assert unit["recovery_hold"] is False
    assert unit["title_status"] == "ACTIVE_TITLE"

    filing = fixtures.read_filing(api, scenario["filing"]["id"])
    assert filing["status"] == "RELEASED"

    borrower = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert borrower["units_under_recovery_hold_count"] == 0
    assert borrower["status"] == "ACTIVE"


def test_net_proceeds_exactly_equal_to_payoff_closes_the_case_settled(api):
    """PRD §3.9: "Then `deficiency_balance_cents` is `payoff_amount_cents` less
    `net_proceeds_cents`, floored at zero, and `surplus_cents` is
    `net_proceeds_cents` less `payoff_amount_cents`, also floored at zero."
    PRD §3.9: "When both `deficiency_balance_cents` and `surplus_cents` are zero,
    the case closes at `CLOSED_SETTLED` and the loan moves from `RECOVERY` to
    `PAID_OFF`."

    Design: Difficulty/boundary_precision_check/settlement_net_proceeds_exactly_equal_payoff_yields_zero_deficiency
    """
    scenario = _case_in_remarketing(api, SETTLED_ASKING_PRICE_CENTS)

    case = fixtures.finalize_sale(
        api, scenario["case"]["id"], SETTLED_RESALE_PRICE_CENTS
    )

    assert case["gross_proceeds_cents"] == SETTLED_RESALE_PRICE_CENTS
    assert case["commission_bps"] == SETTLED_COMMISSION_BPS
    assert case["commission_cents"] == SETTLED_COMMISSION_CENTS
    assert case["net_proceeds_cents"] == SETTLED_NET_PROCEEDS_CENTS
    assert case["payoff_amount_cents"] == SETTLED_PAYOFF_CENTS
    assert case["deficiency_balance_cents"] == 0
    assert case["surplus_cents"] == 0
    assert case["status"] == "CLOSED_SETTLED"

    loan = fixtures.read_loan(api, scenario["loan"]["id"])
    assert loan["servicing_state"] == "PAID_OFF"
    assert_obligation_buckets_zeroed(loan)
    borrower = fixtures.read_borrower(api, scenario["borrower"]["id"])
    assert borrower["total_outstanding_principal_cents"] == 0
    assert borrower["status"] == "ACTIVE"


def test_case_with_no_capitalized_line_reports_zero_refurbishment_cost(api):
    """PRD §3.9: "A case with no capitalized line at all reports
    `refurbishment_cost_cents` as 0."
    PRD §3.9: "The case's `recovery_expense_cents` is seeded with the path's
    expense constant, 185,000 cents for a repossession and 425,000 cents for a
    foreclosure — the foreclosure arm costing well over twice as much because it
    runs through a court."

    Design: Difficulty/boundary_precision_check/settlement_net_proceeds_exactly_equal_payoff_yields_zero_deficiency
    """
    scenario = _case_in_remarketing(api, SETTLED_ASKING_PRICE_CENTS)
    case = scenario["case"]

    assert case["refurbishment_line_items"] == []
    assert case["refurbishment_cost_cents"] == 0
    assert case["recovery_expense_cents"] == REPOSSESSION_EXPENSE_SEED_CENTS
    assert scenario["loan"]["principal_balance_cents"] == PRINCIPAL_CENTS
