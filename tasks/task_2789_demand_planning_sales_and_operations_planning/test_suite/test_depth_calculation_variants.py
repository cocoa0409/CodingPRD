"""Paired calculation variants: two formulas over one input set, and multi-term
formulas whose intermediate rounding and tier pinning cannot be short-circuited.
"""

from test_helpers import TEST_USERS
from test_helpers.assertions import (
    assert_accuracy_record,
    assert_accuracy_summary,
    assert_cycle_money_conserved,
    assert_scenario_closure_chain,
    assert_supply_plan,
)
from test_helpers.fixtures import (
    build_supply_plan,
    create_adjustment,
    create_capacity_scenario,
    evaluate_scenario,
    post_accuracy_record,
    read_accuracy_summary,
    read_cycle,
    read_family,
    read_forecast,
    review_adjustment,
    setup_consensus_promo_fixture,
    setup_gap_fixture,
    setup_two_customer_published_cycle,
    setup_two_policy_cycles,
)

EXEC = TEST_USERS["executive_sponsor_headers"]
LEAD = TEST_USERS["demand_review_lead_headers"]


def test_mape_and_wmape_diverge_over_one_record_set():
    """MAPE is round-then-average while WMAPE is aggregate-then-round, so the same
    two records yield materially different percentages.

    PRD: "The already-rounded per-record `ape_pct` values are summed, divided by
    the number of participating records, and the mean is then rounded half up to
    two decimal places."

    Design: Difficulty/dual_variant_calc/accuracy_mape_vs_wmape_diverge_on_same_records
    """
    ctx = setup_two_customer_published_cycle()

    record_a = post_accuracy_record(
        ctx["cycle"]["id"], ctx["item"]["id"], ctx["customer_a"]["id"], 100
    )
    record_b = post_accuracy_record(
        ctx["cycle"]["id"], ctx["item"]["id"], ctx["customer_b"]["id"], 5000
    )

    assert_accuracy_record(record_a)
    assert record_a["forecast_units_snapshot"] == 130
    assert record_a["signed_error_units"] == 30
    assert record_a["abs_error_units"] == 30
    assert float(record_a["ape_pct"]) == 30.00

    assert_accuracy_record(record_b)
    assert record_b["forecast_units_snapshot"] == 5200
    assert record_b["signed_error_units"] == 200
    assert record_b["abs_error_units"] == 200
    assert float(record_b["ape_pct"]) == 4.00

    summary = read_accuracy_summary(ctx["cycle"]["id"], EXEC)
    assert_accuracy_summary(summary)
    assert summary["record_count"] == 2
    assert summary["total_actual_units"] == 5100
    assert summary["total_abs_error_units"] == 230
    assert float(summary["mape_pct"]) == 17.00
    assert float(summary["wmape_pct"]) == 4.51
    assert float(summary["mape_pct"]) != float(summary["wmape_pct"])


def test_family_rolling_metrics_take_the_volume_weighted_figure():
    """The grade tiers over the weighted metric only, and it is the weighted
    figure that is carried onto the family.

    PRD: "it is the volume-weighted figure — not the unweighted one — that lands
    in a family's `rolling_wmape_pct`."

    Design: Difficulty/dual_variant_calc/accuracy_mape_vs_wmape_diverge_on_same_records
    """
    ctx = setup_two_customer_published_cycle()

    post_accuracy_record(
        ctx["cycle"]["id"], ctx["item"]["id"], ctx["customer_a"]["id"], 100
    )
    post_accuracy_record(
        ctx["cycle"]["id"], ctx["item"]["id"], ctx["customer_b"]["id"], 5000
    )

    summary = read_accuracy_summary(ctx["cycle"]["id"], EXEC)
    assert summary["accuracy_grade"] == "A"
    assert float(summary["bias_pct"]) == 4.51
    assert summary["bias_flag"] == "NONE"

    family = read_family(ctx["family"]["id"])
    assert float(family["rolling_wmape_pct"]) == 4.51
    assert float(family["rolling_bias_pct"]) == 4.51
    assert family["bias_flag"] == "NONE"
    assert family["accuracy_grade"] == "A"
    assert family["scored_record_count"] == 2


def test_net_inventory_first_nets_on_hand_stock_before_clamping():
    """Under the net-inventory policy the on-hand stock comes off the requirement
    first and the clamp is applied to what is left.

    PRD: "Under `NET_INVENTORY_FIRST`, on-hand inventory is netted off the
    requirement *before* the ceilings are applied."

    Design: Difficulty/dual_variant_calc/supply_constraint_net_inventory_first_vs_gross_capacity_first
    """
    ctx = setup_two_policy_cycles()

    assert ctx["item"]["safety_stock_units"] == 330
    assert ctx["item"]["reorder_point_units"] == 1330

    plan = build_supply_plan(ctx["net_cycle"]["id"], ctx["item"]["id"])
    assert_supply_plan(plan)
    assert plan["gross_requirement_units"] == 1000
    assert plan["target_build_units"] == 330
    assert plan["available_units"] == 900
    assert plan["material_cap_units"] == 100000
    assert plan["demand_side_units"] == 830
    assert plan["constrained_units"] == 830
    assert plan["shortfall_units"] == 0
    assert plan["unallocated_units"] == 830
    assert plan["constraint_type"] == "INVENTORY_TARGET"

    cycle = read_cycle(ctx["net_cycle"]["id"])
    assert cycle["plan_value_cents"] == 830000
    assert cycle["constrained_plan_count"] == 1
    assert cycle["posture"] == "AT_RISK"


def test_gross_capacity_first_clamps_before_deducting_on_hand_stock():
    """Under the gross-capacity policy the clamp bites first and the on-hand
    stock is only deducted afterwards, so the same inputs land elsewhere.

    PRD: "Under `GROSS_CAPACITY_FIRST`, the ceilings are applied to the **gross**
    requirement first and on-hand is subtracted afterwards."

    Design: Difficulty/dual_variant_calc/supply_constraint_net_inventory_first_vs_gross_capacity_first
    """
    ctx = setup_two_policy_cycles()

    plan = build_supply_plan(ctx["gross_cycle"]["id"], ctx["item"]["id"])
    assert_supply_plan(plan)
    assert plan["gross_requirement_units"] == 1000
    assert plan["target_build_units"] == 330
    assert plan["available_units"] == 900
    assert plan["material_cap_units"] == 100000
    assert plan["demand_side_units"] == 1330
    assert plan["constrained_units"] == 400
    assert plan["shortfall_units"] == 930
    assert plan["unallocated_units"] == 400
    assert plan["constraint_type"] == "CAPACITY"

    cycle = read_cycle(ctx["gross_cycle"]["id"])
    assert cycle["plan_value_cents"] == 400000
    assert cycle["constrained_plan_count"] == 1
    assert cycle["posture"] == "AT_RISK"


def test_promotion_delta_rounds_the_lift_and_the_cannibalization_apart():
    """Eleven per cent of 333 and four per cent of 333 are each rounded before
    being netted, which is a whole unit away from rounding the netted figure.

    PRD: "Rounding the netted percentage in a single step instead of rounding the
    two terms separately is forbidden"

    Design: Difficulty/combinatorial_formula/consensus_units_per_adjustment_rounding_then_sum
    """
    ctx = setup_consensus_promo_fixture()
    forecast = ctx["forecast"]

    assert forecast["baseline_units"] == 333
    assert forecast["method"] == "HOLT_WINTERS"

    promo_adjustment = create_adjustment(
        forecast["id"],
        forecast["version"],
        adjustment_type="PROMOTION",
        delta_units=0,
        rationale="Q3 feature display",
        promotion_id=ctx["promotion"]["id"],
    )
    promo_adjustment = review_adjustment(
        promo_adjustment["id"], "ENDORSE", review_note="agreed"
    )

    assert promo_adjustment["applied_delta_units"] == 24
    assert promo_adjustment["status"] == "ENDORSED"
    assert promo_adjustment["delta_units"] == 0


def test_consensus_units_sums_the_already_rounded_per_line_deltas():
    """Each adjustment's delta is rounded on its own row and the whole-unit
    results are then added to the baseline.

    PRD: "A consensus adjustment's delta is rounded per adjustment line and the
    already-integer results are then summed"

    Design: Difficulty/combinatorial_formula/consensus_units_per_adjustment_rounding_then_sum
    """
    ctx = setup_consensus_promo_fixture()
    forecast = ctx["forecast"]

    promo_adjustment = create_adjustment(
        forecast["id"],
        forecast["version"],
        adjustment_type="PROMOTION",
        delta_units=0,
        rationale="Q3 feature display",
        promotion_id=ctx["promotion"]["id"],
    )
    review_adjustment(promo_adjustment["id"], "ENDORSE", review_note="agreed")

    reread = read_forecast(forecast["id"])
    sales_adjustment = create_adjustment(
        forecast["id"],
        reread["version"],
        adjustment_type="SALES_INTELLIGENCE",
        delta_units=10,
        rationale="new door count from field sales",
    )
    sales_adjustment = review_adjustment(sales_adjustment["id"], "ENDORSE")
    assert sales_adjustment["applied_delta_units"] == 10

    final = read_forecast(forecast["id"])
    assert final["consensus_units"] == 367
    assert final["endorsed_adjustment_count"] == 2
    assert final["status"] == "UNDER_CONSENSUS"


def test_scenario_trade_rate_tier_reads_only_the_pre_trade_closure():
    """The tier is selected from the pre-trade closure alone, then the spend is
    computed off the gross uplift rather than off the figure that chose the tier.

    PRD: "The trade-spend tier is selected from `pre_trade_closure_cents` and from
    nothing else — selecting it from `gross_uplift_cents` or from the final net
    closure is forbidden."

    Design: Difficulty/combinatorial_formula/scenario_trade_rate_tier_pinned_to_pre_trade_closure
    """
    ctx = setup_gap_fixture()

    plan = ctx["plan"]
    assert plan["constrained_units"] == 1000
    assert plan["shortfall_units"] == 6330
    assert plan["constraint_type"] == "CAPACITY"

    scenario = create_capacity_scenario(
        ctx["cycle"]["id"], ctx["item"]["id"], 52, name="Add second shift"
    )
    scenario = evaluate_scenario(scenario["id"])

    assert scenario["incremental_units"] == 5200
    assert scenario["gross_uplift_cents"] == 5200000
    assert scenario["investment_cost_cents"] == 1300000
    assert scenario["pre_trade_closure_cents"] == 3900000
    assert float(scenario["trade_rate_pct"]) == 6.0
    assert scenario["trade_spend_cents"] == 312000
    assert scenario["net_gap_closure_cents"] == 3588000
    assert scenario["status"] == "EVALUATED"
    assert_scenario_closure_chain(scenario)


def test_scenario_evaluation_leaves_the_cycle_money_alone():
    """The seven derived figures land on the scenario; the cycle's own money
    fields are deliberately untouched by an evaluation.

    PRD: "Evaluating a scenario deliberately does **not** touch the cycle's money
    fields"

    Design: Difficulty/combinatorial_formula/scenario_trade_rate_tier_pinned_to_pre_trade_closure
    """
    ctx = setup_gap_fixture()

    scenario = create_capacity_scenario(
        ctx["cycle"]["id"], ctx["item"]["id"], 52, name="Add second shift"
    )
    evaluate_scenario(scenario["id"])

    cycle = read_cycle(ctx["cycle"]["id"])
    assert cycle["plan_value_cents"] == 1000000
    assert cycle["gross_gap_cents"] == 9000000
    assert cycle["selected_closure_cents"] == 0
    assert cycle["residual_gap_cents"] == 9000000
    assert_cycle_money_conserved(cycle)
