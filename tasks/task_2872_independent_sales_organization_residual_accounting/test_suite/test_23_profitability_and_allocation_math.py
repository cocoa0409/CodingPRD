"""Profitability, override-waterfall and batch-rollup arithmetic.

Every scenario in this module builds its own world through the public endpoints
and then pins the exact cent figures the PRD's arithmetic produces.
"""

from test_helpers import (
    add_line,
    api_client,
    assert_profitability_bottom_lines,
    assert_statement_money_lines_consistent,
    attrite_merchant,
    book_chargeback,
    fetch_agent,
    fetch_batch,
    fetch_line,
    fetch_statement,
    issue_statement,
    list_allocations,
    list_rows,
    make_active_merchant,
    make_agent,
    make_batch,
    make_program,
    normalize_batch,
    notice_and_depart,
    post_batch,
    recall_batch,
    require_statement,
)

NET_PROGRAM = {
    "name": "Atlantic Net Program",
    "buy_rate_bps": 45,
    "buy_rate_per_item_cents": 6,
    "assessment_bps": 13,
    "normalization_mode": "NET_REVENUE_SPLIT",
    "minimum_billing_mode": "NO_MINIMUM",
}


def test_profitability_uses_two_different_chargeback_filters_over_one_event_set():
    """Chargebacks are then aggregated twice over the same event set with two different filters.

    Events booked to any other period are excluded regardless of their `occurred_on`.

    Design: Corner/calculations/profitability_uses_two_different_chargeback_filters_over_one_event_set
    """
    program = make_program(**NET_PROGRAM)
    agent = make_agent(
        name="A1 Principal",
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2024-01-15",
    )
    merchant = make_active_merchant(
        agent["id"],
        program["id"],
        monthly_minimum_cents=0,
        per_transaction_fee_cents=10,
        equipment_lease_monthly_cents=1000,
        boarded_on="2026-04-10",
    )

    # Two July events (one of each liability), one June event, and one event that
    # occurred in July but is booked to August.
    book_chargeback(
        merchant["id"],
        amount_cents=2000,
        occurred_on="2026-07-05",
        period_month="2026-07",
        liability="AGENT_CHARGED",
    )
    book_chargeback(
        merchant["id"],
        amount_cents=3000,
        occurred_on="2026-07-06",
        period_month="2026-07",
        liability="ISO_ABSORBED",
    )
    book_chargeback(
        merchant["id"],
        amount_cents=5000,
        occurred_on="2026-06-28",
        period_month="2026-06",
        liability="AGENT_CHARGED",
    )
    book_chargeback(
        merchant["id"],
        amount_cents=900,
        occurred_on="2026-07-30",
        period_month="2026-08",
        liability="AGENT_CHARGED",
    )

    batch = make_batch(
        program["id"],
        period_month="2026-07",
        coverage_start="2026-07-01",
        coverage_end="2026-08-01",
    )
    line = add_line(
        batch["id"],
        merchant["id"],
        transaction_count=100,
        sales_volume_cents=1000000,
        interchange_cents=20000,
        assessments_cents=1300,
        gross_income_cents=40000,
    )
    normalize_batch(batch["id"])

    line = fetch_line(line["id"])
    assert line["processor_cost_cents"] == 5100, (
        "the volume term rounds on its own before the per-item term is added: "
        f"expected 5100, got {line['processor_cost_cents']}"
    )
    assert line["normalized_net_revenue_cents"] == 13600, (
        "NET_REVENUE_SPLIT deducts the processor cost at the line: expected "
        f"13600, got {line['normalized_net_revenue_cents']}"
    )

    post_batch(batch["id"])

    rows, meta = list_rows(
        api_client.list_merchant_profitability, {"residual_batch_id": batch["id"]}
    )
    assert meta["total_count"] == 1, (
        f"one line means one profitability row, got total_count {meta['total_count']}"
    )
    row = rows[0]
    assert row["period_month"] == "2026-07", (
        f"the row is keyed on the batch period, got {row['period_month']}"
    )
    assert row["chargeback_cost_cents"] == 5000, (
        "chargeback_cost_cents sums both liabilities for period 2026-07 only: "
        f"expected 5000, got {row['chargeback_cost_cents']}"
    )
    assert row["agent_chargeable_chargeback_cents"] == 2000, (
        "agent_chargeable_chargeback_cents keeps only AGENT_CHARGED events of the "
        f"period: expected 2000, got {row['agent_chargeable_chargeback_cents']}"
    )
    assert row["equipment_cost_cents"] == 1000, (
        "an ACTIVE merchant is charged the full monthly lease: expected 1000, got "
        f"{row['equipment_cost_cents']}"
    )
    assert row["profit_cents"] == 7600, (
        f"profit_cents expected 7600, got {row['profit_cents']}"
    )
    assert row["agent_basis_cents"] == 10600, (
        "the split basis absorbs only the agent-charged chargeback: expected "
        f"10600, got {row['agent_basis_cents']}"
    )
    assert row["profit_cents"] != row["agent_basis_cents"], (
        "the two bottom lines must diverge by the 3000-cent ISO_ABSORBED event"
    )
    assert row["allocated_total_cents"] == 5300, (
        f"allocated_total_cents expected 5300, got {row['allocated_total_cents']}"
    )
    assert row["iso_retained_cents"] == 5300, (
        f"iso_retained_cents expected 5300, got {row['iso_retained_cents']}"
    )
    assert_profitability_bottom_lines(row)

    allocations, alloc_meta = list_rows(
        api_client.list_residual_allocations, {"merchant_id": merchant["id"]}
    )
    assert alloc_meta["total_count"] == 1, (
        f"a single direct tier was paid, got total_count {alloc_meta['total_count']}"
    )
    allocation = allocations[0]
    assert allocation["allocation_type"] == "DIRECT_SPLIT", (
        f"expected DIRECT_SPLIT, got {allocation['allocation_type']}"
    )
    assert allocation["tier_level"] == 0, (
        f"the direct tier is tier_level 0, got {allocation['tier_level']}"
    )
    assert float(allocation["applied_pct"]) == 0.50, (
        f"applied_pct expected 0.50, got {allocation['applied_pct']}"
    )
    assert allocation["basis_cents"] == 10600, (
        f"basis_cents expected 10600, got {allocation['basis_cents']}"
    )
    assert allocation["gross_allocation_cents"] == 5300, (
        f"gross_allocation_cents expected 5300, got {allocation['gross_allocation_cents']}"
    )
    assert allocation["vesting_withheld_cents"] == 0, (
        "an ACTIVE agent withholds nothing: expected 0, got "
        f"{allocation['vesting_withheld_cents']}"
    )

    statement = require_statement(agent["id"], "2026-07")
    assert statement["direct_residual_cents"] == 5300, (
        f"direct_residual_cents expected 5300, got {statement['direct_residual_cents']}"
    )
    assert statement["net_payable_cents"] == 5300, (
        f"net_payable_cents expected 5300, got {statement['net_payable_cents']}"
    )


def test_minimum_true_up_skips_attrited_merchants_and_halves_the_agent_share():
    """For each such allocation, take the merchant it points at and the processor program that merchant is boarded on, and skip the merchant entirely in two cases: when its `status` is anything other than `ACTIVE` at issue time (an attrited merchant owes no minimum, even if it produced a line for the period), and when its program's `minimum_billing_mode` is `NO_MINIMUM`.

    The agent's share of that shortfall is the shortfall multiplied by the agent's
    `split_pct` multiplied by one half, rounded half up to the cent.

    Design: Corner/calculations/minimum_true_up_skips_attrited_merchants_and_halves_the_agent_share
    """
    program = make_program(
        name="Shortfall Billed Program",
        buy_rate_bps=45,
        buy_rate_per_item_cents=6,
        assessment_bps=13,
        normalization_mode="NET_REVENUE_SPLIT",
        minimum_billing_mode="SHORTFALL_BILLED",
    )
    agent = make_agent(
        name="A1 Principal",
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2024-01-15",
    )
    merchant_one = make_active_merchant(
        agent["id"],
        program["id"],
        monthly_minimum_cents=5000,
        per_transaction_fee_cents=10,
        equipment_lease_monthly_cents=0,
        boarded_on="2026-04-10",
    )
    merchant_two = make_active_merchant(
        agent["id"],
        program["id"],
        monthly_minimum_cents=5000,
        per_transaction_fee_cents=10,
        equipment_lease_monthly_cents=0,
        boarded_on="2026-04-10",
    )

    batch = make_batch(
        program["id"],
        period_month="2026-07",
        coverage_start="2026-07-01",
        coverage_end="2026-08-01",
    )
    add_line(
        batch["id"],
        merchant_one["id"],
        transaction_count=100,
        sales_volume_cents=1000000,
        interchange_cents=20000,
        assessments_cents=1300,
        gross_income_cents=40000,
    )
    add_line(
        batch["id"],
        merchant_two["id"],
        transaction_count=200,
        sales_volume_cents=500000,
        interchange_cents=10000,
        assessments_cents=650,
        gross_income_cents=20000,
    )
    normalize_batch(batch["id"])
    post_batch(batch["id"])

    # The second merchant closes after the post, so its line stays in the ledger
    # while the merchant itself leaves the minimum-reconciliation input set.
    attrite_merchant(merchant_two["id"], "2026-07-20")

    statement = require_statement(agent["id"], "2026-07")
    assert statement["direct_residual_cents"] == 9750, (
        "6800 from the first merchant plus 2950 from the second: expected 9750, "
        f"got {statement['direct_residual_cents']}"
    )
    assert statement["minimum_true_up_cents"] == 0, (
        "a DRAFT statement forces the true-up to zero, got "
        f"{statement['minimum_true_up_cents']}"
    )
    assert statement["net_payable_cents"] == 9750, (
        f"net_payable_cents expected 9750 before the issue, got {statement['net_payable_cents']}"
    )
    assert statement["settlement_state"] == "HELD", (
        "one of two qualifying merchants attrited is exactly 5,000 bps, so the "
        f"statement moves to HELD, got {statement['settlement_state']}"
    )
    assert statement["hold_reason"] == "PORTFOLIO_ATTRITION_THRESHOLD", (
        f"hold_reason expected PORTFOLIO_ATTRITION_THRESHOLD, got {statement['hold_reason']}"
    )

    issued = issue_statement(statement["id"])
    assert issued["lifecycle_state"] == "ISSUED", (
        "a held statement can still be issued, got lifecycle_state "
        f"{issued['lifecycle_state']}"
    )
    assert issued["minimum_true_up_cents"] == 1000, (
        "only the still-ACTIVE merchant contributes: round_half_up(4000 x 0.50 x 0.5) "
        f"is 1000, got {issued['minimum_true_up_cents']}"
    )
    assert issued["minimum_true_up_cents"] != 1750, (
        "1750 would mean the attrited merchant's 750-cent share was counted"
    )
    assert issued["gross_after_trueup_cents"] == 10750, (
        f"gross_after_trueup_cents expected 10750, got {issued['gross_after_trueup_cents']}"
    )
    assert issued["advance_recoupment_cents"] == 0, (
        f"no advances exist, so expected 0, got {issued['advance_recoupment_cents']}"
    )
    assert issued["net_payable_cents"] == 10750, (
        f"net_payable_cents expected 10750, got {issued['net_payable_cents']}"
    )
    assert issued["carry_forward_deficit_cents"] == 0, (
        f"carry_forward_deficit_cents expected 0, got {issued['carry_forward_deficit_cents']}"
    )
    assert_statement_money_lines_consistent(issued)

    refreshed_agent = fetch_agent(agent["id"])
    assert refreshed_agent["trailing_residual_cents"] == 10750, (
        "the KPI sums gross_after_trueup_cents: expected 10750, got "
        f"{refreshed_agent['trailing_residual_cents']}"
    )


def test_departed_agent_allocation_is_scaled_by_frozen_vesting():
    """Second, decide what is actually paid: if the receiving agent's `status` is `DEPARTED`, the amount paid is the basis multiplied by the tier percentage multiplied by that agent's `vested_pct_at_departure`, divided by one hundred, rounded half up to the cent; otherwise the amount paid equals the raw entitlement.

    That single figure absorbs three different things at once: the percentage
    points no tier claimed, every cent withheld from a departed agent by vesting,
    and every rounding remainder from the independently rounded tiers.

    Design: Corner/calculations/departed_agent_allocation_is_scaled_by_frozen_vesting
    """
    program = make_program(**NET_PROGRAM)
    agent = make_agent(
        name="A1 Departing",
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2024-01-15",
    )
    merchant = make_active_merchant(
        agent["id"],
        program["id"],
        monthly_minimum_cents=0,
        per_transaction_fee_cents=10,
        equipment_lease_monthly_cents=1000,
        boarded_on="2026-04-10",
    )

    # Notice and departure both land on the logical clock's current date, and the
    # book is deliberately left with the departing agent.
    departed = notice_and_depart(agent["id"], "2026-08-01")
    assert departed["status"] == "DEPARTED", (
        f"expected status DEPARTED, got {departed['status']}"
    )
    assert departed["vested_pct_at_departure"] == 50, (
        "thirty elapsed months against the 2026-08-01 clock vest two 25-point "
        f"steps: expected 50, got {departed['vested_pct_at_departure']}"
    )

    _, adjustment_meta = list_rows(api_client.list_statement_adjustments, {})
    assert adjustment_meta["total_count"] == 0, (
        "with no ISSUED or FINALIZED statement the buyout is 0 and no adjustment "
        f"is created, got total_count {adjustment_meta['total_count']}"
    )

    batch = make_batch(
        program["id"],
        period_month="2026-07",
        coverage_start="2026-07-01",
        coverage_end="2026-08-01",
    )
    add_line(
        batch["id"],
        merchant["id"],
        transaction_count=100,
        sales_volume_cents=1000000,
        interchange_cents=20000,
        assessments_cents=1300,
        gross_income_cents=67400,
    )
    normalize_batch(batch["id"])
    post_batch(batch["id"])

    rows, _ = list_rows(
        api_client.list_merchant_profitability, {"residual_batch_id": batch["id"]}
    )
    row = rows[0]
    assert row["agent_basis_cents"] == 40000, (
        f"41000 of net revenue less a 1000-cent lease: expected 40000, got {row['agent_basis_cents']}"
    )
    assert row["profit_cents"] == 40000, (
        f"profit_cents expected 40000, got {row['profit_cents']}"
    )

    allocations, alloc_meta = list_rows(
        api_client.list_residual_allocations,
        {"agent_id": agent["id"], "period_month": "2026-07"},
    )
    assert alloc_meta["total_count"] == 1, (
        f"one direct tier only, got total_count {alloc_meta['total_count']}"
    )
    allocation = allocations[0]
    assert float(allocation["applied_pct"]) == 0.50, (
        "applied_pct records the nominal tier percentage, unscaled by vesting: "
        f"expected 0.50, got {allocation['applied_pct']}"
    )
    assert allocation["basis_cents"] == 40000, (
        f"basis_cents expected 40000, got {allocation['basis_cents']}"
    )
    assert allocation["gross_allocation_cents"] == 10000, (
        "the amount paid is scaled by the frozen 50 percent: expected 10000, got "
        f"{allocation['gross_allocation_cents']}"
    )
    assert allocation["vesting_withheld_cents"] == 10000, (
        "the raw 20000-cent entitlement less the 10000 paid: expected 10000, got "
        f"{allocation['vesting_withheld_cents']}"
    )
    assert row["allocated_total_cents"] == 10000, (
        f"allocated_total_cents sums what was paid: expected 10000, got {row['allocated_total_cents']}"
    )
    assert row["iso_retained_cents"] == 30000, (
        "the withheld half falls to the house rather than to another agent: "
        f"expected 30000, got {row['iso_retained_cents']}"
    )

    statement = require_statement(agent["id"], "2026-07")
    assert statement["direct_residual_cents"] == 10000, (
        f"direct_residual_cents expected 10000, got {statement['direct_residual_cents']}"
    )
    assert statement["gross_after_trueup_cents"] == 10000, (
        f"gross_after_trueup_cents expected 10000, got {statement['gross_after_trueup_cents']}"
    )
    assert statement["net_payable_cents"] == 10000, (
        f"net_payable_cents expected 10000, got {statement['net_payable_cents']}"
    )
    assert statement["lifecycle_state"] == "DRAFT", (
        f"a posting cascade creates statements in DRAFT, got {statement['lifecycle_state']}"
    )
    assert fetch_agent(agent["id"])["trailing_residual_cents"] == 10000, (
        "trailing_residual_cents expected 10000 after the cascade"
    )


def test_override_walk_visits_three_ancestors_and_a_zero_differential_burns_one():
    """The walk then climbs the hierarchy by following `parent_agent_id` upward, visiting at most three ancestors and stopping early if the chain runs out.

    Each visit is numbered from 1 upward, and that visit number becomes the
    `tier_level` of any row it writes.

    Design: Corner/calculations/override_walk_visits_three_ancestors_and_a_zero_differential_burns_one
    """
    program = make_program(**NET_PROGRAM)
    a1 = make_agent(
        name="A1 Root", split_pct=0.20, override_pct=0.60, vesting_start_date="2024-01-15"
    )
    a2 = make_agent(
        name="A2 Level1",
        split_pct=0.25,
        override_pct=0.55,
        vesting_start_date="2024-01-15",
        parent_agent_id=a1["id"],
    )
    a3 = make_agent(
        name="A3 Level2",
        split_pct=0.30,
        override_pct=0.45,
        vesting_start_date="2024-01-15",
        parent_agent_id=a2["id"],
    )
    a4 = make_agent(
        name="A4 Level3",
        split_pct=0.35,
        override_pct=0.45,
        vesting_start_date="2024-01-15",
        parent_agent_id=a3["id"],
    )
    a5 = make_agent(
        name="A5 Producer",
        split_pct=0.40,
        override_pct=0.40,
        vesting_start_date="2024-01-15",
        parent_agent_id=a4["id"],
    )
    for expected_depth, agent in enumerate((a1, a2, a3, a4, a5)):
        assert agent["hierarchy_depth"] == expected_depth, (
            f"the five-tier chain must sit at depths 0..4, got "
            f"{agent['hierarchy_depth']} for {agent['name']}"
        )

    merchant = make_active_merchant(
        a5["id"],
        program["id"],
        monthly_minimum_cents=0,
        per_transaction_fee_cents=10,
        equipment_lease_monthly_cents=0,
        boarded_on="2026-04-10",
    )
    batch = make_batch(
        program["id"],
        period_month="2026-07",
        coverage_start="2026-07-01",
        coverage_end="2026-08-01",
    )
    add_line(
        batch["id"],
        merchant["id"],
        transaction_count=100,
        sales_volume_cents=1000000,
        interchange_cents=0,
        assessments_cents=0,
        gross_income_cents=45100,
    )
    normalize_batch(batch["id"])
    post_batch(batch["id"])

    allocations, alloc_meta = list_rows(
        api_client.list_residual_allocations, {"period_month": "2026-07"}
    )
    assert alloc_meta["total_count"] == 3, (
        "the direct tier plus two paid ancestors, not four and not five: got "
        f"total_count {alloc_meta['total_count']}"
    )
    by_agent = {row["agent_id"]: row for row in allocations}

    direct = by_agent[a5["id"]]
    assert direct["allocation_type"] == "DIRECT_SPLIT", (
        f"the owning agent takes the direct tier, got {direct['allocation_type']}"
    )
    assert direct["tier_level"] == 0, f"expected tier_level 0, got {direct['tier_level']}"
    assert float(direct["applied_pct"]) == 0.40, (
        f"applied_pct expected 0.40, got {direct['applied_pct']}"
    )
    assert direct["basis_cents"] == 40000, (
        f"basis_cents expected 40000, got {direct['basis_cents']}"
    )
    assert direct["gross_allocation_cents"] == 16000, (
        f"gross_allocation_cents expected 16000, got {direct['gross_allocation_cents']}"
    )

    first_override = by_agent[a4["id"]]
    assert first_override["allocation_type"] == "OVERRIDE", (
        f"expected OVERRIDE, got {first_override['allocation_type']}"
    )
    assert first_override["tier_level"] == 1, (
        f"the first visited ancestor is tier_level 1, got {first_override['tier_level']}"
    )
    assert float(first_override["applied_pct"]) == 0.05, (
        f"0.45 less the running 0.40: expected 0.05, got {first_override['applied_pct']}"
    )
    assert first_override["gross_allocation_cents"] == 2000, (
        f"gross_allocation_cents expected 2000, got {first_override['gross_allocation_cents']}"
    )

    assert a3["id"] not in by_agent, (
        "the middle ancestor's differential is max(0, 0.45 - 0.45) == 0, so no row "
        "is written for it"
    )
    assert all(row["tier_level"] != 2 for row in allocations), (
        "visit 2 paid nothing, so no allocation may carry tier_level 2"
    )

    second_override = by_agent[a2["id"]]
    assert second_override["allocation_type"] == "OVERRIDE", (
        f"expected OVERRIDE, got {second_override['allocation_type']}"
    )
    assert second_override["tier_level"] == 3, (
        "tier_level records the visit index, so the third visit is 3 even though "
        f"visit 2 paid nothing, got {second_override['tier_level']}"
    )
    assert float(second_override["applied_pct"]) == 0.10, (
        f"0.55 less the running 0.45: expected 0.10, got {second_override['applied_pct']}"
    )
    assert second_override["gross_allocation_cents"] == 4000, (
        f"gross_allocation_cents expected 4000, got {second_override['gross_allocation_cents']}"
    )

    assert a1["id"] not in by_agent, (
        "the three visits were consumed on A4, A3 and A2, so the root earns nothing"
    )
    assert fetch_statement(a1["id"], "2026-07") is None, (
        "no allocation attached to the root agent, so it has no statement"
    )

    rows, _ = list_rows(
        api_client.list_merchant_profitability, {"residual_batch_id": batch["id"]}
    )
    row = rows[0]
    assert row["agent_basis_cents"] == 40000, (
        f"agent_basis_cents expected 40000, got {row['agent_basis_cents']}"
    )
    assert row["allocated_total_cents"] == 22000, (
        f"16000 + 2000 + 4000: expected 22000, got {row['allocated_total_cents']}"
    )
    assert row["iso_retained_cents"] == 18000, (
        f"iso_retained_cents expected 18000, got {row['iso_retained_cents']}"
    )

    statements, statement_meta = list_rows(
        api_client.list_agent_statements, {"period_month": "2026-07"}
    )
    assert statement_meta["total_count"] == 3, (
        f"one statement per paid agent, got total_count {statement_meta['total_count']}"
    )
    gross_by_agent = {row["agent_id"]: row["gross_after_trueup_cents"] for row in statements}
    assert gross_by_agent[a5["id"]] == 16000, (
        f"A5 gross_after_trueup_cents expected 16000, got {gross_by_agent[a5['id']]}"
    )
    assert gross_by_agent[a4["id"]] == 2000, (
        f"A4 gross_after_trueup_cents expected 2000, got {gross_by_agent[a4['id']]}"
    )
    assert gross_by_agent[a2["id"]] == 4000, (
        f"A2 gross_after_trueup_cents expected 4000, got {gross_by_agent[a2['id']]}"
    )


def test_half_cent_allocations_round_half_up_and_the_remainder_stays_with_the_house():
    """When a merchant's split basis is divided across a direct agent and several override tiers, each tier is rounded independently and whatever pennies fall out of the arithmetic land in the ISO's retained residue, never in another agent's pocket.

    take the smaller of that active-day count and the number of days in the
    period, multiply `equipment_lease_monthly_cents` by it, divide by the number
    of days in the period, and round half up to the cent.

    Design: Corner/calculations/half_cent_allocations_round_half_up_and_the_remainder_stays_with_the_house
    """
    program = make_program(**NET_PROGRAM)
    agent = make_agent(
        name="A1 Principal",
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2024-01-15",
    )
    merchant_a = make_active_merchant(
        agent["id"],
        program["id"],
        monthly_minimum_cents=0,
        per_transaction_fee_cents=10,
        equipment_lease_monthly_cents=0,
        boarded_on="2026-04-10",
    )
    merchant_b = make_active_merchant(
        agent["id"],
        program["id"],
        monthly_minimum_cents=0,
        per_transaction_fee_cents=10,
        equipment_lease_monthly_cents=501,
        boarded_on="2026-04-10",
    )
    attrite_merchant(merchant_b["id"], "2026-06-15")

    batch = make_batch(
        program["id"],
        period_month="2026-06",
        coverage_start="2026-06-01",
        coverage_end="2026-07-01",
    )
    line_a = add_line(
        batch["id"],
        merchant_a["id"],
        transaction_count=100,
        sales_volume_cents=1000000,
        interchange_cents=0,
        assessments_cents=0,
        gross_income_cents=8433,
    )
    line_b = add_line(
        batch["id"],
        merchant_b["id"],
        transaction_count=100,
        sales_volume_cents=1000000,
        interchange_cents=0,
        assessments_cents=0,
        gross_income_cents=15100,
    )
    batch = normalize_batch(batch["id"])

    line_a = fetch_line(line_a["id"])
    line_b = fetch_line(line_b["id"])
    assert line_a["processor_cost_cents"] == 5100, (
        f"processor_cost_cents expected 5100, got {line_a['processor_cost_cents']}"
    )
    assert line_a["normalized_net_revenue_cents"] == 3333, (
        f"normalized_net_revenue_cents expected 3333, got {line_a['normalized_net_revenue_cents']}"
    )
    assert line_b["processor_cost_cents"] == 5100, (
        f"processor_cost_cents expected 5100, got {line_b['processor_cost_cents']}"
    )
    assert line_b["normalized_net_revenue_cents"] == 10000, (
        f"normalized_net_revenue_cents expected 10000, got {line_b['normalized_net_revenue_cents']}"
    )
    assert batch["line_count"] == 2, f"line_count expected 2, got {batch['line_count']}"
    assert batch["gross_volume_cents"] == 2000000, (
        f"gross_volume_cents expected 2000000, got {batch['gross_volume_cents']}"
    )
    assert batch["total_normalized_net_revenue_cents"] == 13333, (
        "the batch total sums the already-rounded per-line results: expected 13333, "
        f"got {batch['total_normalized_net_revenue_cents']}"
    )

    post_batch(batch["id"])

    rows_b, _ = list_rows(
        api_client.list_merchant_profitability, {"merchant_id": merchant_b["id"]}
    )
    row_b = rows_b[0]
    assert row_b["equipment_cost_cents"] == 251, (
        "fifteen active days of thirty at a 501-cent lease is 250.5, which rounds "
        f"up: expected 251, got {row_b['equipment_cost_cents']}"
    )
    assert row_b["agent_basis_cents"] == 9749, (
        f"agent_basis_cents expected 9749, got {row_b['agent_basis_cents']}"
    )
    alloc_b = list_allocations(merchant_id=merchant_b["id"])[0]
    assert alloc_b["gross_allocation_cents"] == 4875, (
        "round_half_up(9749 x 0.50) is 4875, not 4874: got "
        f"{alloc_b['gross_allocation_cents']}"
    )
    assert row_b["iso_retained_cents"] == 4874, (
        f"iso_retained_cents expected 4874, got {row_b['iso_retained_cents']}"
    )

    rows_a, _ = list_rows(
        api_client.list_merchant_profitability, {"merchant_id": merchant_a["id"]}
    )
    row_a = rows_a[0]
    assert row_a["equipment_cost_cents"] == 0, (
        f"no lease on this merchant: expected 0, got {row_a['equipment_cost_cents']}"
    )
    assert row_a["agent_basis_cents"] == 3333, (
        f"agent_basis_cents expected 3333, got {row_a['agent_basis_cents']}"
    )
    alloc_a = list_allocations(merchant_id=merchant_a["id"])[0]
    assert alloc_a["gross_allocation_cents"] == 1667, (
        "round_half_up(3333 x 0.50) is 1667, not 1666: got "
        f"{alloc_a['gross_allocation_cents']}"
    )
    assert row_a["iso_retained_cents"] == 1666, (
        f"iso_retained_cents expected 1666, got {row_a['iso_retained_cents']}"
    )

    for allocation in (alloc_a, alloc_b):
        assert allocation["vesting_withheld_cents"] == 0, (
            "the agent is ACTIVE, so nothing is withheld: got "
            f"{allocation['vesting_withheld_cents']}"
        )
    for row in (row_a, row_b):
        assert row["allocated_total_cents"] + row["iso_retained_cents"] == row["agent_basis_cents"], (
            "the basis is fully accounted for by the paid tiers plus the house residue"
        )

    statement = require_statement(agent["id"], "2026-06")
    assert statement["direct_residual_cents"] == 6542, (
        "1667 + 4875, each rounded on its own: expected 6542, got "
        f"{statement['direct_residual_cents']}"
    )
    assert statement["net_payable_cents"] == 6542, (
        f"net_payable_cents expected 6542, got {statement['net_payable_cents']}"
    )

    posted_batch = fetch_batch(batch["id"])
    assert posted_batch["iso_retained_cents"] == 6540, (
        f"1666 + 4874: expected 6540, got {posted_batch['iso_retained_cents']}"
    )


def test_batch_totals_are_round_then_sum_and_survive_a_recall_and_an_append():
    """Once every line has been normalized, the batch rolls up: `line_count` becomes the number of lines attached to the batch, `gross_volume_cents` becomes the sum of their `sales_volume_cents` values, and `total_normalized_net_revenue_cents` becomes the sum of their `normalized_net_revenue_cents` values.

    Appending raises the batch's `line_count` by one and bumps the batch's
    `version`; the line's own normalization outputs are not yet computed, so
    `processor_cost_cents` and `normalized_net_revenue_cents` sit at 0 and
    `normalization_mode_applied` is null.

    Recall resets `processor_cost_cents` and `normalized_net_revenue_cents` to 0
    and `normalization_mode_applied` to null on every line of the batch.

    A batch with no lines at all normalizes successfully, and all three totals
    stay at 0.

    Design: Corner/calculations/batch_totals_are_round_then_sum_and_survive_a_recall_and_an_append
    """
    program = make_program(**NET_PROGRAM)
    agent = make_agent(
        name="A1 Principal",
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2024-01-15",
    )
    merchants = [
        make_active_merchant(
            agent["id"],
            program["id"],
            monthly_minimum_cents=0,
            per_transaction_fee_cents=10,
            equipment_lease_monthly_cents=0,
            boarded_on="2026-04-10",
        )
        for _ in range(3)
    ]
    batch = make_batch(
        program["id"],
        period_month="2026-07",
        coverage_start="2026-07-01",
        coverage_end="2026-08-01",
    )

    # Each line carries a 1,000-cent volume, whose buy-rate product is exactly
    # 4.5 cents, so round-then-sum and sum-then-round disagree from two lines on.
    thin_line = {
        "transaction_count": 1,
        "sales_volume_cents": 1000,
        "interchange_cents": 0,
        "assessments_cents": 0,
        "gross_income_cents": 6000,
    }
    add_line(batch["id"], merchants[0]["id"], **thin_line)
    add_line(batch["id"], merchants[1]["id"], **thin_line)

    ingested = fetch_batch(batch["id"])
    assert ingested["line_count"] == 2, (
        f"each append raises line_count by one: expected 2, got {ingested['line_count']}"
    )
    assert ingested["gross_volume_cents"] == 0, (
        "the append computes no money at all: expected 0, got "
        f"{ingested['gross_volume_cents']}"
    )
    assert ingested["total_normalized_net_revenue_cents"] == 0, (
        "the append computes no money at all: expected 0, got "
        f"{ingested['total_normalized_net_revenue_cents']}"
    )

    normalized = normalize_batch(batch["id"])
    lines, line_meta = list_rows(
        api_client.list_residual_lines, {"residual_batch_id": batch["id"]}
    )
    assert line_meta["total_count"] == 2, (
        f"two lines on the batch, got total_count {line_meta['total_count']}"
    )
    for line in lines:
        assert line["processor_cost_cents"] == 11, (
            "round_half_up(1000 x 45 / 10000) is 5, plus 6 x 1 per item: expected "
            f"11, got {line['processor_cost_cents']}"
        )
        assert line["normalized_net_revenue_cents"] == 5989, (
            f"6000 less the 11-cent cost: expected 5989, got {line['normalized_net_revenue_cents']}"
        )
    assert normalized["line_count"] == 2, (
        f"line_count expected 2, got {normalized['line_count']}"
    )
    assert normalized["gross_volume_cents"] == 2000, (
        f"gross_volume_cents expected 2000, got {normalized['gross_volume_cents']}"
    )
    assert normalized["total_normalized_net_revenue_cents"] == 11978, (
        "round-then-sum gives 11978 while summing the raw volumes first would give "
        f"11979: got {normalized['total_normalized_net_revenue_cents']}"
    )

    recalled = recall_batch(batch["id"])
    assert recalled["state"] == "RECEIVED", (
        f"recall returns the batch to RECEIVED, got {recalled['state']}"
    )
    assert recalled["recall_count"] == 1, (
        f"recall_count expected 1, got {recalled['recall_count']}"
    )
    assert recalled["total_normalized_net_revenue_cents"] == 0, (
        "the recall clears the normalization total: expected 0, got "
        f"{recalled['total_normalized_net_revenue_cents']}"
    )
    assert recalled["line_count"] == 2, (
        "line_count describes the file and survives the recall: expected 2, got "
        f"{recalled['line_count']}"
    )
    recalled_lines, recalled_line_meta = list_rows(
        api_client.list_residual_lines, {"residual_batch_id": batch["id"]}
    )
    assert recalled_line_meta["total_count"] == 2, (
        "a recall never deletes lines: expected total_count 2, got "
        f"{recalled_line_meta['total_count']}"
    )
    for line in recalled_lines:
        assert line["processor_cost_cents"] == 0, (
            f"the recall resets processor_cost_cents to 0, got {line['processor_cost_cents']}"
        )
        assert line["normalized_net_revenue_cents"] == 0, (
            "the recall resets normalized_net_revenue_cents to 0, got "
            f"{line['normalized_net_revenue_cents']}"
        )
        assert line["normalization_mode_applied"] is None, (
            "the recall resets normalization_mode_applied to null, got "
            f"{line['normalization_mode_applied']}"
        )

    add_line(batch["id"], merchants[2]["id"], **thin_line)
    renormalized = normalize_batch(batch["id"])
    assert renormalized["line_count"] == 3, (
        f"line_count expected 3, got {renormalized['line_count']}"
    )
    assert renormalized["gross_volume_cents"] == 3000, (
        f"gross_volume_cents expected 3000, got {renormalized['gross_volume_cents']}"
    )
    assert renormalized["total_normalized_net_revenue_cents"] == 17967, (
        "round-then-sum gives 5989 x 3 == 17967 while summing the raw volumes "
        f"first would give 17968: got {renormalized['total_normalized_net_revenue_cents']}"
    )

    post_batch(batch["id"])
    posted = fetch_batch(batch["id"])
    assert posted["iso_retained_cents"] == 8982, (
        "per line the house keeps 5989 - 2995 == 2994, three times over: expected "
        f"8982, got {posted['iso_retained_cents']}"
    )
    statement = require_statement(agent["id"], "2026-07")
    assert statement["direct_residual_cents"] == 8985, (
        "round_half_up(5989 x 0.50) is 2995, three times over: expected 8985, got "
        f"{statement['direct_residual_cents']}"
    )
    assert statement["direct_residual_cents"] + posted["iso_retained_cents"] == 17967, (
        "the agent share plus the house residue must reconstruct the batch total "
        "exactly, with no rounding drift"
    )

    empty_batch = make_batch(
        program["id"],
        period_month="2026-06",
        coverage_start="2026-06-01",
        coverage_end="2026-07-01",
    )
    empty_normalized = normalize_batch(empty_batch["id"])
    assert empty_normalized["state"] == "NORMALIZED", (
        f"an empty batch normalizes successfully, got state {empty_normalized['state']}"
    )
    assert empty_normalized["line_count"] == 0, (
        f"line_count expected 0, got {empty_normalized['line_count']}"
    )
    assert empty_normalized["gross_volume_cents"] == 0, (
        f"gross_volume_cents expected 0, got {empty_normalized['gross_volume_cents']}"
    )
    assert empty_normalized["total_normalized_net_revenue_cents"] == 0, (
        f"total_normalized_net_revenue_cents expected 0, got "
        f"{empty_normalized['total_normalized_net_revenue_cents']}"
    )

    _, batch_meta = list_rows(
        api_client.list_residual_batches, {"processor_program_id": program["id"]}
    )
    assert batch_meta["total_count"] == 2, (
        f"both batches belong to the program, got total_count {batch_meta['total_count']}"
    )
    programs, program_meta = list_rows(
        api_client.list_processor_programs, {"status": "ACTIVE"}
    )
    assert program_meta["total_count"] == 1, (
        f"one ACTIVE program exists, got total_count {program_meta['total_count']}"
    )
    assert programs[0]["posted_batch_count"] == 1, (
        "only the posted batch counts towards posted_batch_count: expected 1, got "
        f"{programs[0]['posted_batch_count']}"
    )
