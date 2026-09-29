"""Two-branch cascades and the inclusive boundaries: attrition, vesting and minimums."""

from test_helpers import (
    ADMIN,
    CONTROLLER,
    add_thin_line,
    api_client,
    attrite_merchant_payload,
    depart_agent,
    fetch_agent,
    fetch_line,
    fetch_merchant,
    fetch_statement_by_id,
    file_notice,
    issue_statement,
    list_adjustments,
    list_allocations,
    list_profitability,
    list_rows,
    make_active_merchant,
    make_agent,
    make_batch,
    make_program,
    normalize_batch,
    post_batch,
    require_statement,
    set_logical_clock,
    setup_canonical_posted_period,
    setup_hierarchy_posted_period,
    validate_success,
)

BONUS = {"upfront_bonus_cents": 25000}


def _posted_then_attrited() -> dict:
    """The 2026-07 batch is already POSTED when A3's only merchant closes on 2026-07-20."""
    scenario = setup_hierarchy_posted_period(merchant_overrides=dict(BONUS))
    scenario["statement"] = require_statement(scenario["a3"]["id"])
    assert fetch_agent(scenario["a3"]["id"])["portfolio_attrition_bps"] == 0
    validate_success(
        api_client.attrite_merchant(
            scenario["merchant"]["id"], attrite_merchant_payload("2026-07-20"), ADMIN
        )
    )
    return scenario


def test_attrition_claws_back_the_prorated_bonus_through_a_system_adjustment():
    """101 active days of a 270-day window leave 15648 cents to reclaim.

    round_half_up(25000 * (270 - 101) / 270) = 15648, applied as a negative
    BONUS_CLAWBACK that floors the 14643 statement at zero and carries 1005.

    PRD: "the clawback is `upfront_bonus_cents` multiplied by the number of days
    remaining in the window (270 minus the days the merchant was active), divided
    by 270, rounded half up to the cent"

    Design: Difficulty/transitive_cascade/merchant_attrite_cascade_three_links_to_portfolio_hold
    """
    scenario = _posted_then_attrited()

    adjustments = list_adjustments(statement_id=scenario["statement"]["id"])
    assert len(adjustments) == 1
    clawback = adjustments[0]
    assert clawback["kind"] == "BONUS_CLAWBACK"
    assert clawback["amount_cents"] == -15648
    assert clawback["state"] == "APPLIED"
    assert clawback["created_by_user_id"] == "system"
    assert clawback["source_merchant_id"] == scenario["merchant"]["id"]

    statement = fetch_statement_by_id(scenario["statement"]["id"])
    assert statement["adjustment_cents"] == -15648
    assert statement["gross_after_trueup_cents"] == 14643, "the gross is unchanged"
    assert statement["net_payable_cents"] == 0
    assert statement["carry_forward_deficit_cents"] == 1005

    assert fetch_agent(scenario["a3"]["id"])["lifetime_clawback_cents"] == 15648
    assert fetch_merchant(scenario["merchant"]["id"])["clawed_back_bonus_cents"] == 15648
    assert fetch_agent(scenario["a3"]["id"])["trailing_residual_cents"] == 14643, (
        "the KPI tracks gross, so a clawback must not touch it"
    )


def test_the_same_attrition_trips_the_risk_hold_without_rewriting_posted_history():
    """One of one merchant gone is 10000 bps, so the DRAFT statement is force-held.

    PRD: "every statement of that agent whose `lifecycle_state` is `DRAFT` or
    `ISSUED` and whose `settlement_state` is `UNSETTLED` is moved along the
    settlement dimension from `UNSETTLED` to `HELD`, with `hold_reason` recorded
    as `PORTFOLIO_ATTRITION_THRESHOLD`"

    Design: Difficulty/transitive_cascade/merchant_attrite_cascade_three_links_to_portfolio_hold
    """
    scenario = _posted_then_attrited()

    owner = fetch_agent(scenario["a3"]["id"])
    assert owner["portfolio_attrition_bps"] == 10000
    assert owner["residual_hold"] is True

    statement = fetch_statement_by_id(scenario["statement"]["id"])
    assert statement["settlement_state"] == "HELD"
    assert statement["hold_reason"] == "PORTFOLIO_ATTRITION_THRESHOLD"
    assert statement["lifecycle_state"] == "DRAFT", "the lifecycle dimension is untouched"

    rows = list_profitability(residual_batch_id=scenario["batch"]["id"])
    assert len(rows) == 1
    assert rows[0]["equipment_cost_cents"] == 3900, "a posted row is never repriced"
    assert rows[0]["agent_basis_cents"] == 32539
    direct = [
        row
        for row in list_allocations(merchant_id=scenario["merchant"]["id"])
        if row["allocation_type"] == "DIRECT_SPLIT"
    ]
    assert direct[0]["gross_allocation_cents"] == 14643

    assert fetch_agent(scenario["a2"]["id"])["residual_hold"] is False
    assert fetch_agent(scenario["a1"]["id"])["residual_hold"] is False


def _two_agents_departing_at_the_cliff() -> dict:
    """A3's anchor is exactly twelve months before the clock; A4's is eleven."""
    scenario = setup_canonical_posted_period(
        agent_overrides={"name": "A3 Cliff Reached", "vesting_start_date": "2026-02-01"}
    )
    scenario["a4"] = make_agent(name="A4 Cliff Missed", vesting_start_date="2026-03-01")
    scenario["july_statement"] = issue_statement(scenario["statement"]["id"])

    set_logical_clock("2027-02-01T00:00:00Z")
    file_notice(scenario["agent"]["id"], "2027-02-01")
    file_notice(scenario["a4"]["id"], "2027-02-01")
    depart_agent(scenario["agent"]["id"])
    depart_agent(scenario["a4"]["id"])
    return scenario


def test_exactly_twelve_elapsed_months_vests_and_buys_out_the_trailing_average():
    """A 2026-02-01 anchor against a 2027-02-01 clock vests 25 and buys out 87858.

    The trailing window holds one ISSUED statement, so the average is 14643 and
    14643 * 24 * 25 / 100 = 87858 exactly.

    PRD: "The cliff boundary is inclusive at twelve: exactly twelve elapsed months
    returns 25, while eleven returns 0."

    Design: Difficulty/boundary_precision_check/vesting_cliff_at_exactly_twelve_months_on_departure
    """
    scenario = _two_agents_departing_at_the_cliff()

    departed = fetch_agent(scenario["agent"]["id"])
    assert departed["status"] == "DEPARTED"
    assert departed["vested_pct_at_departure"] == 25
    assert departed["vested_pct"] == 25

    rows, meta = list_rows(
        api_client.list_agent_statements,
        {"agent_id": scenario["agent"]["id"], "period_month": "2027-02"},
    )
    assert meta["total_count"] == 1
    buyout_statement = rows[0]
    assert buyout_statement["lifecycle_state"] == "DRAFT"
    assert buyout_statement["settlement_state"] == "UNSETTLED"
    assert buyout_statement["adjustment_cents"] == 87858
    assert buyout_statement["net_payable_cents"] == 87858

    adjustments = list_adjustments(statement_id=buyout_statement["id"])
    assert len(adjustments) == 1
    buyout = adjustments[0]
    assert buyout["kind"] == "VESTED_BUYOUT"
    assert buyout["amount_cents"] == 87858
    assert buyout["state"] == "APPLIED"
    assert buyout["created_by_user_id"] == "system"
    assert buyout["source_merchant_id"] is None


def test_eleven_elapsed_months_vests_nothing_and_creates_no_statement_at_all():
    """One calendar day of anchor difference separates 87858 from nothing.

    PRD: "An agent with zero vesting buys out at exactly 0, and no adjustment is
    created when the buyout evaluates to 0."

    Design: Difficulty/boundary_precision_check/vesting_cliff_at_exactly_twelve_months_on_departure
    """
    scenario = _two_agents_departing_at_the_cliff()

    missed = fetch_agent(scenario["a4"]["id"])
    assert missed["status"] == "DEPARTED"
    assert missed["vested_pct_at_departure"] == 0
    assert missed["vested_pct"] == 0

    _, meta = list_rows(
        api_client.list_agent_statements, {"agent_id": scenario["a4"]["id"]}
    )
    assert meta["total_count"] == 0, "a 0% buyout upserts nothing"

    all_adjustments = list_adjustments()
    buyouts = [row for row in all_adjustments if row["kind"] == "VESTED_BUYOUT"]
    assert len(buyouts) == 1, "only the vested agent produced a buyout"

    july = fetch_statement_by_id(scenario["july_statement"]["id"])
    assert july["gross_after_trueup_cents"] == 14643
    assert july["lifecycle_state"] == "ISSUED", "the trailing average source is untouched"


def _exact_and_short_minimum_period() -> dict:
    """Two agents whose merchants bill 2500 and 2480 cents of fee income."""
    program = make_program(minimum_billing_mode="SHORTFALL_BILLED")
    ax = make_agent(name="AX Exact", split_pct=0.45, override_pct=0.45)
    ay = make_agent(name="AY Short", split_pct=0.45, override_pct=0.45)
    thin_pricing = {
        "monthly_minimum_cents": 2500,
        "per_transaction_fee_cents": 20,
        "equipment_lease_monthly_cents": 0,
        "boarded_on": "2026-01-05",
    }
    mx = make_active_merchant(ax["id"], program["id"], **thin_pricing)
    my = make_active_merchant(ay["id"], program["id"], **thin_pricing)
    batch = make_batch(program["id"], file_checksum="sha256:min-0001")
    lx = add_thin_line(batch["id"], mx["id"], transaction_count=125)
    ly = add_thin_line(batch["id"], my["id"], transaction_count=124)
    normalize_batch(batch["id"])
    post_batch(batch["id"])
    statement_x = require_statement(ax["id"])
    statement_y = require_statement(ay["id"])
    validate_success(api_client.issue_agent_statement(statement_x["id"], CONTROLLER))
    validate_success(api_client.issue_agent_statement(statement_y["id"], CONTROLLER))
    return {
        "lx": lx,
        "ly": ly,
        "statement_x": fetch_statement_by_id(statement_x["id"]),
        "statement_y": fetch_statement_by_id(statement_y["id"]),
    }


def test_fee_income_exactly_equal_to_the_minimum_bills_nothing():
    """125 authorizations at 20 cents bill exactly 2500, so the shortfall is zero.

    PRD: "the comparison is inclusive, so billable fee income exactly equal to the
    monthly minimum yields a shortfall of zero and bills nothing"

    Design: Difficulty/boundary_precision_check/monthly_minimum_billable_fee_exactly_covers_minimum
    """
    scenario = _exact_and_short_minimum_period()

    assert fetch_line(scenario["lx"]["id"])["normalized_net_revenue_cents"] == 70

    exact = scenario["statement_x"]
    assert exact["direct_residual_cents"] == 32, "round_half_up(70 * 0.45)"
    assert exact["minimum_true_up_cents"] == 0
    assert exact["gross_after_trueup_cents"] == 32
    assert exact["net_payable_cents"] == 32


def test_one_authorization_short_bills_a_half_cent_share_rounded_up_to_five():
    """A 20-cent shortfall gives the agent round_half_up(20 * 0.45 * 0.5) = 5, not 4.

    The missing authorization also saves 6 cents of per-item buy rate, so the line
    normalizes to 76 instead of 70 and the direct split is 34.

    PRD: "The agent's share of that shortfall is the shortfall multiplied by the
    agent's `split_pct` multiplied by one half, rounded half up to the cent."

    Design: Difficulty/boundary_precision_check/monthly_minimum_billable_fee_exactly_covers_minimum
    """
    scenario = _exact_and_short_minimum_period()

    assert fetch_line(scenario["ly"]["id"])["normalized_net_revenue_cents"] == 76

    short = scenario["statement_y"]
    assert short["direct_residual_cents"] == 34
    assert short["minimum_true_up_cents"] == 5
    assert short["gross_after_trueup_cents"] == 39
    assert short["net_payable_cents"] == 39
