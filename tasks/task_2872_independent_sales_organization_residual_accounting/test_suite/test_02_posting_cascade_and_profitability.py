"""Posting a batch: equipment proration, the override waterfall and the four cascade links."""

from test_helpers import (
    CONTROLLER,
    api_client,
    attrite_merchant,
    fetch_agent,
    fetch_batch,
    fetch_program,
    list_allocations,
    list_profitability,
    list_rows,
    post_batch,
    require_statement,
    setup_hierarchy_posted_period,
    validate_success,
)

BONUS = {"upfront_bonus_cents": 25000}


def _attrited_mid_period_scenario() -> dict:
    """The three-level hierarchy with M1 attrited on 2026-07-20 before the post."""
    scenario = setup_hierarchy_posted_period(merchant_overrides=dict(BONUS), post=False)
    attrite_merchant(scenario["merchant"]["id"], "2026-07-20")
    scenario["batch"] = post_batch(scenario["batch"]["id"])
    return scenario


def _profitability_row(batch_id: str) -> dict:
    rows = list_profitability(residual_batch_id=batch_id)
    assert len(rows) == 1, f"expected exactly one profitability row, got {len(rows)}"
    return rows[0]


def _allocations_by_tier(merchant_id: str) -> dict:
    rows = list_allocations(merchant_id=merchant_id)
    assert len(rows) == 3, f"expected three allocations, got {len(rows)}"
    return {row["tier_level"]: row for row in rows}


def test_equipment_lease_is_prorated_for_a_merchant_that_went_dark_mid_period():
    """M1 closes on 2026-07-20, so 20 of July's 31 days are charged: 2516 cents.

    round_half_up(3900 * 20 / 31) = 2516, not the full 3900 an ACTIVE merchant
    pays and not the 0 a merchant that closed in an earlier month pays.

    PRD: "multiply `equipment_lease_monthly_cents` by it, divide by the number of
    days in the period, and round half up to the cent"

    Design: Difficulty/combinatorial_formula/profitability_equipment_proration_nested_conditional
    """
    scenario = _attrited_mid_period_scenario()

    row = _profitability_row(scenario["batch"]["id"])
    assert row["equipment_cost_cents"] == 2516
    assert row["chargeback_cost_cents"] == 16500, "both liabilities count against profit"
    assert row["agent_chargeable_chargeback_cents"] == 4500
    assert row["profit_cents"] == 21923, "40939 - 16500 - 2516"
    assert row["agent_basis_cents"] == 33923, "40939 - 4500 - 2516"


def test_the_prorated_basis_rescales_every_tier_and_the_clawback_lands_on_the_statement():
    """The 1384-cent equipment saving flows into all three tiers and the house residue.

    A3 takes 0.45 of 33923 = 15265, A2 the 0.05 differential = 1696 and A1 the
    next 0.05 differential = 1696, leaving 15266 with the house. The 2026-07-20
    attrition also claws back round_half_up(25000 * 169 / 270) = 15648.

    PRD: "the differential entitlement is the ancestor's `override_pct` minus the
    running cumulative percentage, or zero if that difference would be negative"

    Design: Difficulty/combinatorial_formula/profitability_equipment_proration_nested_conditional
    """
    scenario = _attrited_mid_period_scenario()

    tiers = _allocations_by_tier(scenario["merchant"]["id"])
    assert tiers[0]["agent_id"] == scenario["a3"]["id"]
    assert tiers[0]["allocation_type"] == "DIRECT_SPLIT"
    assert float(tiers[0]["applied_pct"]) == 0.45
    assert tiers[0]["gross_allocation_cents"] == 15265
    assert tiers[1]["agent_id"] == scenario["a2"]["id"]
    assert tiers[1]["allocation_type"] == "OVERRIDE"
    assert float(tiers[1]["applied_pct"]) == 0.05
    assert tiers[1]["gross_allocation_cents"] == 1696
    assert tiers[2]["agent_id"] == scenario["a1"]["id"]
    assert tiers[2]["allocation_type"] == "OVERRIDE"
    assert float(tiers[2]["applied_pct"]) == 0.05
    assert tiers[2]["gross_allocation_cents"] == 1696

    row = _profitability_row(scenario["batch"]["id"])
    assert row["iso_retained_cents"] == 15266, "33923 - 15265 - 1696 - 1696"

    statement = require_statement(scenario["a3"]["id"])
    assert statement["adjustment_cents"] == -15648
    assert statement["net_payable_cents"] == 0
    assert statement["carry_forward_deficit_cents"] == 383, "15648 - 15265"


def test_one_post_walks_from_the_line_to_the_profitability_row_and_the_three_tiers():
    """Cascade links 1 and 2: one line becomes one profitability row and three allocations.

    Basis 32539 pays A3 14643 at 0.45, then A2 and A1 1627 each at their 0.05
    differentials, leaving 14642 with the house.

    PRD: "A successful post writes `posted_at` from the logical clock, raises the
    governing program's `posted_batch_count` by one, and then runs a four-level
    cascade."

    Design: Difficulty/transitive_cascade/batch_post_cascade_four_links_to_agent_kpi
    """
    scenario = setup_hierarchy_posted_period(merchant_overrides=dict(BONUS), post=False)

    validate_success(api_client.post_residual_batch(scenario["batch"]["id"], CONTROLLER))

    row = _profitability_row(scenario["batch"]["id"])
    assert row["normalized_net_revenue_cents"] == 40939
    assert row["chargeback_cost_cents"] == 16500
    assert row["equipment_cost_cents"] == 3900, "an ACTIVE merchant pays the full lease"
    assert row["profit_cents"] == 20539
    assert row["agent_basis_cents"] == 32539

    tiers = _allocations_by_tier(scenario["merchant"]["id"])
    assert tiers[0]["agent_id"] == scenario["a3"]["id"]
    assert tiers[0]["allocation_type"] == "DIRECT_SPLIT"
    assert tiers[0]["gross_allocation_cents"] == 14643
    assert tiers[1]["agent_id"] == scenario["a2"]["id"]
    assert tiers[1]["allocation_type"] == "OVERRIDE"
    assert tiers[1]["gross_allocation_cents"] == 1627
    assert tiers[2]["agent_id"] == scenario["a1"]["id"]
    assert tiers[2]["allocation_type"] == "OVERRIDE"
    assert tiers[2]["gross_allocation_cents"] == 1627
    for tier in tiers.values():
        assert tier["basis_cents"] == 32539
        assert tier["vesting_withheld_cents"] == 0

    assert row["allocated_total_cents"] == 17897, "14643 + 1627 + 1627"
    assert row["iso_retained_cents"] == 14642


def test_the_post_upserts_all_three_statements_and_refreshes_every_agent_kpi():
    """Cascade links 3 and 4: three DRAFT statements and three trailing-residual KPIs.

    PRD: "Each statement recompute in turn refreshes `trailing_residual_cents` on
    that statement's agent."

    Design: Difficulty/transitive_cascade/batch_post_cascade_four_links_to_agent_kpi
    """
    scenario = setup_hierarchy_posted_period(merchant_overrides=dict(BONUS), post=False)

    post_batch(scenario["batch"]["id"])

    rows, meta = list_rows(api_client.list_agent_statements, {"period_month": "2026-07"})
    assert meta["total_count"] == 3
    for statement in rows:
        assert statement["lifecycle_state"] == "DRAFT"
        assert statement["settlement_state"] == "UNSETTLED"
        assert statement["minimum_true_up_cents"] == 0
        assert statement["advance_recoupment_cents"] == 0

    bottom = require_statement(scenario["a3"]["id"])
    assert bottom["direct_residual_cents"] == 14643
    assert bottom["override_residual_cents"] == 0
    assert bottom["gross_after_trueup_cents"] == 14643
    assert bottom["net_payable_cents"] == 14643
    for key in ("a2", "a1"):
        upline = require_statement(scenario[key]["id"])
        assert upline["direct_residual_cents"] == 0
        assert upline["override_residual_cents"] == 1627
        assert upline["net_payable_cents"] == 1627

    assert fetch_agent(scenario["a3"]["id"])["trailing_residual_cents"] == 14643
    assert fetch_agent(scenario["a2"]["id"])["trailing_residual_cents"] == 1627
    assert fetch_agent(scenario["a1"]["id"])["trailing_residual_cents"] == 1627

    batch = fetch_batch(scenario["batch"]["id"])
    assert batch["state"] == "POSTED"
    assert batch["iso_retained_cents"] == 14642
    assert batch["posted_at"] is not None
    assert fetch_program(scenario["program"]["id"])["posted_batch_count"] == 1
