"""Multi-hop cascades that reach promotions, adjustments, consensus lines, plans,
allocations and cycle money in one request, and the conservation identities that
have to survive the compensating writes.
"""

from test_helpers.assertions import (
    assert_allocation_units_conserved,
    assert_cycle_money_conserved,
    assert_cycle_posture,
)
from test_helpers.fixtures import (
    list_plan_allocations,
    read_adjustment,
    read_cycle,
    read_forecast,
    read_plan,
    read_promotion,
    read_scenario,
    reset_inventory_policy,
    select_scenario,
    setup_five_customer_rationing,
    setup_runout_cascade_fixture,
    setup_two_customer_rationed_plan,
    setup_two_evaluated_scenarios_fixture,
    transition_cycle,
    transition_item,
)
from test_helpers.test_users import make_executive_sponsor_headers

EXEC = make_executive_sponsor_headers("exec-1")


def test_runout_truncates_only_the_months_beyond_the_runout_boundary():
    """The month comparison is strict, so the line for the runout month itself
    survives while every later line is truncated to zero consensus.

    PRD: "the boundary is strict: a line for exactly the `runout_end_month`
    survives, a line for the month after it is truncated."

    Design: Difficulty/transitive_cascade/item_runout_cascades_to_promotion_then_adjustment_then_consensus
    """
    ctx = setup_runout_cascade_fixture()

    before_nov = read_forecast(ctx["fc_nov"]["id"])
    assert before_nov["consensus_units"] == 1100

    item = transition_item(ctx["item"]["id"], "RUNOUT", runout_end_month="2026-09")
    assert item["lifecycle_state"] == "RUNOUT"
    assert item["runout_end_month"] == "2026-09"

    september = read_forecast(ctx["fc_sep"]["id"])
    assert september["status"] == "CONSENSUS_LOCKED"
    assert september["consensus_units"] == 1000

    october = read_forecast(ctx["fc_oct"]["id"])
    assert october["status"] == "RUNOUT_TRUNCATED"
    assert october["consensus_units"] == 0

    november = read_forecast(ctx["fc_nov"]["id"])
    assert november["status"] == "RUNOUT_TRUNCATED"
    assert november["consensus_units"] == 0


def test_runout_cascade_cancels_the_promotion_voids_its_adjustment_and_stales_the_plan():
    """Hop one cancels the late promotion, hop two voids the adjustment that cited
    it and re-rolls the line, and the staleness sweep reaches the allocations and
    the cycle's money.

    PRD: "every consensus adjustment of type `PROMOTION` whose `promotion_id` is
    that cancelled promotion and whose status is `PROPOSED`, `ENDORSED` or
    `COMMITTED` transitions to `VOIDED` with its `applied_delta_units` set to 0"

    Design: Difficulty/transitive_cascade/item_runout_cascades_to_promotion_then_adjustment_then_consensus
    """
    ctx = setup_runout_cascade_fixture()

    before_plan = read_plan(ctx["plan"]["id"])
    assert before_plan["gross_requirement_units"] == 3100
    assert before_plan["constrained_units"] == 900
    assert before_plan["constraint_type"] == "CAPACITY"
    assert before_plan["status"] == "RATIONED"
    before_cycle = read_cycle(ctx["cycle"]["id"])
    assert before_cycle["plan_value_cents"] == 900000
    assert before_cycle["posture"] == "AT_RISK"

    transition_item(ctx["item"]["id"], "RUNOUT", runout_end_month="2026-09")

    promotion = read_promotion(ctx["promotion"]["id"])
    assert promotion["status"] == "CANCELLED_RUNOUT"

    adjustment = read_adjustment(ctx["adjustment"]["id"])
    assert adjustment["status"] == "VOIDED"
    assert adjustment["applied_delta_units"] == 0
    assert read_forecast(ctx["fc_nov"]["id"])["endorsed_adjustment_count"] == 0

    plan = read_plan(ctx["plan"]["id"])
    assert plan["status"] == "STALE"
    assert plan["requires_replan"] is True
    allocations = list_plan_allocations(ctx["plan"]["id"])
    assert allocations
    for row in allocations:
        assert row["allocation_status"] == "VOIDED"
        assert row["allocated_units"] == 0

    cycle = read_cycle(ctx["cycle"]["id"])
    assert cycle["plan_value_cents"] == 0
    assert cycle["constrained_plan_count"] == 0
    assert cycle["residual_gap_cents"] == 0
    assert cycle["posture"] == "GREEN"
    assert_cycle_posture(cycle)


def test_policy_reset_recomputes_the_safety_stock_and_the_reorder_point():
    """A tighter service level, a higher variability and a longer lead time move
    the item onto the top z tier, and the reorder point ceilings its cycle-stock
    term before adding the already-ceilinged safety stock.

    PRD: "A reorder point ceilings its cycle-stock term first and adds the
    already-ceilinged safety stock to it, rather than ceilinging the sum in one
    pass."

    Design: Difficulty/transitive_cascade/inventory_policy_change_cascades_to_allocations_and_cycle_gap
    """
    ctx = setup_five_customer_rationing()

    assert ctx["item"]["safety_stock_units"] == 330

    item = reset_inventory_policy(ctx["item"]["id"], 99.0, 0.50, 60)
    assert item["safety_stock_units"] == 1648
    assert item["reorder_point_units"] == 3648


def test_policy_reset_stales_the_plan_voids_its_allocations_and_zeroes_the_plan_value():
    """The reset invalidates the plan that snapshotted the old safety stock, which
    compensates every allocation row and removes the plan from the cycle's value.

    PRD: "Every supply plan of that item which is not already `STALE` is therefore
    invalidated by the reset: it transitions to `STALE`, its `requires_replan`
    flag is set to true"

    Design: Difficulty/transitive_cascade/inventory_policy_change_cascades_to_allocations_and_cycle_gap
    """
    ctx = setup_five_customer_rationing()

    before_plan = read_plan(ctx["plan"]["id"])
    assert before_plan["status"] == "RATIONED"
    assert before_plan["constrained_units"] == 900
    assert before_plan["unallocated_units"] == 0
    before_cycle = read_cycle(ctx["cycle"]["id"])
    assert before_cycle["plan_value_cents"] == 900000
    assert before_cycle["constrained_plan_count"] == 1
    assert before_cycle["posture"] == "AT_RISK"

    reset_inventory_policy(ctx["item"]["id"], 99.0, 0.50, 60)

    plan = read_plan(ctx["plan"]["id"])
    assert plan["status"] == "STALE"
    assert plan["requires_replan"] is True
    assert plan["unallocated_units"] == 900
    assert plan["constrained_units"] == 900

    allocations = list_plan_allocations(ctx["plan"]["id"])
    assert len(allocations) == 5
    # PRD 3.6: "every one of its rows whose allocation_status is ALLOCATED
    # transitions to VOIDED with allocated_units reset to 0 ... Rows already in
    # WITHHELD_CREDIT_HOLD are left as they are."
    by_customer = {row["customer_id"]: row for row in allocations}
    held = by_customer[ctx["c4"]["id"]]
    assert held["allocation_status"] == "WITHHELD_CREDIT_HOLD"
    assert held["allocated_units"] == 0
    for customer in (ctx["c1"], ctx["c2"], ctx["c3"], ctx["c5"]):
        row = by_customer[customer["id"]]
        assert row["allocation_status"] == "VOIDED"
        assert row["allocated_units"] == 0
        assert row["fill_rate_pct"] == 0.00
        assert row["allocation_pass"] == "NONE"
    # PRD 2.10 conservation survives the compensation exactly.
    assert (
        sum(row["allocated_units"] for row in allocations)
        + plan["unallocated_units"]
        == plan["constrained_units"]
    )

    cycle = read_cycle(ctx["cycle"]["id"])
    assert cycle["plan_value_cents"] == 0
    assert cycle["gross_gap_cents"] == 0
    assert cycle["selected_closure_cents"] == 0
    assert cycle["residual_gap_cents"] == 0
    assert cycle["constrained_plan_count"] == 0
    assert cycle["posture"] == "GREEN"


def test_void_restores_the_leftover_to_the_full_constrained_quantity():
    """Compensation moves the granted units back into the leftover rather than
    rewriting the constrained quantity, and nothing is deleted.

    PRD: "while the plan's `unallocated_units` is restored to the full
    `constrained_units`."

    Design: Difficulty/compensating_invariant/allocation_void_preserves_constrained_units_conservation
    """
    ctx = setup_two_customer_rationed_plan()

    before_plan = read_plan(ctx["plan"]["id"])
    assert before_plan["constrained_units"] == 900
    assert before_plan["status"] == "RATIONED"
    assert before_plan["unallocated_units"] == 0

    transition_cycle(ctx["cycle"]["id"], "SCENARIO_REVIEW")
    transition_cycle(ctx["cycle"]["id"], "EXECUTIVE_REVIEW")
    transition_cycle(
        ctx["cycle"]["id"],
        "DEMAND_REVIEW",
        EXEC,
        reopen_reason="club channel volume withdrawn",
    )

    plan = read_plan(ctx["plan"]["id"])
    assert plan["unallocated_units"] == 900
    assert plan["constrained_units"] == 900
    assert plan["status"] == "STALE"
    assert plan["requires_replan"] is True

    allocations = list_plan_allocations(ctx["plan"]["id"])
    assert len(allocations) == 2
    for row in allocations:
        assert row["allocation_status"] == "VOIDED"
        assert row["allocated_units"] == 0

    assert read_cycle(ctx["cycle"]["id"])["reopen_count"] == 1


def test_allocation_conservation_survives_the_compensation_exactly():
    """Granted units plus leftover equal the constrained quantity both after
    rationing and after every row has been voided.

    PRD: "The sum of `allocated_units` across all of that plan's allocation rows,
    plus the plan's `unallocated_units`, always equals the plan's
    `constrained_units`."

    Design: Difficulty/compensating_invariant/allocation_void_preserves_constrained_units_conservation
    """
    ctx = setup_two_customer_rationed_plan()

    before_plan = read_plan(ctx["plan"]["id"])
    before_rows = list_plan_allocations(ctx["plan"]["id"])
    assert sorted(row["allocated_units"] for row in before_rows) == [400, 500]
    assert_allocation_units_conserved(before_plan, before_rows)

    transition_cycle(ctx["cycle"]["id"], "SCENARIO_REVIEW")
    transition_cycle(ctx["cycle"]["id"], "EXECUTIVE_REVIEW")
    transition_cycle(
        ctx["cycle"]["id"],
        "DEMAND_REVIEW",
        EXEC,
        reopen_reason="club channel volume withdrawn",
    )

    after_plan = read_plan(ctx["plan"]["id"])
    after_rows = list_plan_allocations(ctx["plan"]["id"])
    assert len(after_rows) == 2
    assert_allocation_units_conserved(after_plan, after_rows)
    assert read_cycle(ctx["cycle"]["id"])["plan_value_cents"] == 0


def test_second_selection_of_the_same_type_displaces_the_first_and_rewrites_the_closure():
    """Two plays of the same type cannot both be live, so selecting the second one
    supersedes the first and the cycle's closure money is recomputed from the
    survivor alone.

    PRD: "any **other** scenario of the same cycle with the same `scenario_type`
    and a status of `SELECTED` transitions to `SUPERSEDED`"

    Design: Difficulty/compensating_invariant/scenario_supersede_restores_residual_gap_identity
    """
    ctx = setup_two_evaluated_scenarios_fixture()

    first = read_scenario(ctx["first_scenario"]["id"])
    assert first["net_gap_closure_cents"] == 3588000
    assert first["status"] == "SELECTED"
    before_cycle = read_cycle(ctx["cycle"]["id"])
    assert before_cycle["selected_closure_cents"] == 3588000
    assert before_cycle["residual_gap_cents"] == 5412000

    second = read_scenario(ctx["second_scenario"]["id"])
    assert second["incremental_units"] == 2000
    assert second["gross_uplift_cents"] == 2000000
    assert second["investment_cost_cents"] == 500000
    assert second["pre_trade_closure_cents"] == 1500000
    assert float(second["trade_rate_pct"]) == 6.0
    assert second["trade_spend_cents"] == 120000
    assert second["net_gap_closure_cents"] == 1380000

    selected = select_scenario(second["id"], before_cycle["version"])
    assert selected["status"] == "SELECTED"
    assert selected["selected_by_user_id"] == "exec-1"

    cycle = read_cycle(ctx["cycle"]["id"])
    assert cycle["selected_closure_cents"] == 1380000
    assert cycle["residual_gap_cents"] == 7620000
    assert cycle["version"] == before_cycle["version"] + 1
    assert cycle["posture"] == "AT_RISK"
    assert_cycle_money_conserved(cycle)


def test_superseded_scenario_keeps_the_closure_it_was_evaluated_at():
    """Being displaced removes the closure from the cycle without rewriting the
    scenario's own evaluated figure.

    PRD: "The scenario's own `net_gap_closure_cents` field keeps the value it was
    evaluated at; it simply stops counting."

    Design: Difficulty/compensating_invariant/scenario_supersede_restores_residual_gap_identity
    """
    ctx = setup_two_evaluated_scenarios_fixture()

    cycle_before = read_cycle(ctx["cycle"]["id"])
    select_scenario(ctx["second_scenario"]["id"], cycle_before["version"])

    superseded = read_scenario(ctx["first_scenario"]["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["net_gap_closure_cents"] == 3588000

    cycle = read_cycle(ctx["cycle"]["id"])
    assert cycle["selected_closure_cents"] == 1380000
    assert_cycle_money_conserved(cycle)
