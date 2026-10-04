"""Launch quantity planning: both variants computed at creation (demand vs
risk-adjusted divergence on a decaying trend) and the pinned single-pass
budget clamp at quantity lock.
"""

import pytest

from test_helpers import (
    assert_launch_inventory_conserved,
    assert_launch_plan,
    read_launch_plan,
    setup_draft_plan,
    setup_locked_plan,
)


def test_capacity_and_markdown_risk_computed_at_plan_creation(api):
    """PRD §3.8: "First, `capacity_units` — the most the shelf can sell through:
    the slot's `facings` multiplied by twelve units of weekly sell-through per
    facing, multiplied by the eight-week launch window. Second,
    `markdown_risk_pct` — the decay risk of a trend item: the number of whole
    weeks between the parent trend's `created_at` and the plan's `created_at`,
    multiplied by five percent per week, capped at forty percent"
    Slot 10 facings -> 10*12*8 == 960; trend 2026-09-01 to plan 2026-10-02 is
    31 days -> 4 whole weeks -> 0.20.

    Design: Difficulty/dual_variant_calc/launch_qty_demand_vs_risk_adjusted_diverge
    """
    ctx = setup_draft_plan()
    plan = ctx["plan"]

    assert_launch_plan(plan)
    assert plan["capacity_units"] == 960
    assert plan["markdown_risk_pct"] == pytest.approx(0.20, abs=0.005)
    assert plan["status"] == "DRAFT"
    assert plan["sampling_status"] == "NONE"


def test_demand_and_risk_adjusted_variants_diverge_at_creation(api):
    """PRD §3.8: "From these, both quantity variants are computed and stored at
    creation: the demand-projection variant `qty_demand_variant_units` is the
    smaller of `demand_forecast_units` and `capacity_units`, and the
    risk-adjusted variant `qty_risk_variant_units` is the smaller of the floor
    of `demand_forecast_units` reduced by `markdown_risk_pct` and
    `capacity_units`."
    Demand 800 -> min(800, 960) == 800; risk-adjusted -> min(floor(800*0.8),
    960) == 640 — the variants diverge because risk 0.20 bites and capacity
    does not.

    Design: Difficulty/dual_variant_calc/launch_qty_demand_vs_risk_adjusted_diverge
    """
    ctx = setup_draft_plan()
    plan = read_launch_plan(ctx["plan"]["id"])

    assert plan["qty_demand_variant_units"] == 800
    assert plan["qty_risk_variant_units"] == 640
    assert plan["qty_demand_variant_units"] != plan["qty_risk_variant_units"]
    assert plan["qty_locked_units"] is None


def test_budget_clamp_is_single_pass_evaluated_at_moq(api):
    """PRD §3.8: "Otherwise the clamp applies once: the landed cost is evaluated
    a single time at the manufacturer's minimum order quantity, the budget is
    divided by that figure and floored to a whole unit count, and if that
    floored count falls below the minimum order quantity the lock is rejected
    with `ERR_BUDGET_EXCEEDED`; otherwise the floored count becomes
    `qty_locked_units`."
    Demand 2000 -> capacity-clamped candidate 960; 960 * landed(960)=235 ==
    225600 > 200000 triggers one clamp: floor(200000 / landed(500)=244) == 819.
    No fixed-point iteration: landed_locked_cents is then evaluated at 819 as
    200 + ceil(10000/819)=13 + 4 + 20 == 237.

    Design: Difficulty/combinatorial_formula/launch_qty_budget_clamp_single_pass
    """
    ctx = setup_locked_plan(plan_overrides={"demand_forecast_units": 2000})
    plan = read_launch_plan(ctx["plan"]["id"])

    assert plan["qty_demand_variant_units"] == 960
    assert plan["qty_locked_units"] == 819
    assert plan["landed_locked_cents"] == 237
    assert 819 * 244 <= 200000 < 820 * 244


def test_clamped_lock_records_variant_and_respects_moq(api):
    """PRD §3.8: "The lock records `locked_variant` and stores
    `landed_locked_cents`, the landed unit cost at the locked quantity."
    PRD §3.8: "In either branch, a locked quantity below the manufacturer's
    minimum is rejected with `ERR_BELOW_MOQ`."
    The clamped quantity 819 still meets the manufacturer's 500-unit MOQ, so
    the lock succeeds and inventory conservation holds from the lock onward.

    Design: Difficulty/combinatorial_formula/launch_qty_budget_clamp_single_pass
    """
    ctx = setup_locked_plan(plan_overrides={"demand_forecast_units": 2000})
    plan = ctx["plan"]

    assert plan["status"] == "QUANTITY_LOCKED"
    assert plan["locked_variant"] == "DEMAND"
    assert plan["qty_locked_units"] == 819
    assert plan["qty_locked_units"] >= ctx["manufacturer"]["moq_units"]
    assert_launch_inventory_conserved(read_launch_plan(plan["id"]))
