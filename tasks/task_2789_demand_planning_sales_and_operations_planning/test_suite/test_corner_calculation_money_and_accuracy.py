"""Arithmetic breadth on the money and accountability side: the two scenario
variants and their trade-spend tiers, the record sets that feed a cycle's money
roll-up and its posture gate, and the error metrics rolled up at two scopes.
"""

from test_helpers.assertions import (
    assert_accuracy_record,
    assert_accuracy_summary,
    assert_cycle_money_conserved,
    assert_cycle_posture,
    assert_scenario,
    assert_scenario_closure_chain,
)
from test_helpers.fixtures import (
    EXEC,
    advance_cycle_to,
    build_supply_plan,
    create_capacity_block,
    create_capacity_scenario,
    create_customer,
    create_cycle,
    create_family,
    create_forecast,
    create_item,
    create_item_with_defaults,
    create_price_scenario,
    evaluate_scenario,
    post_accuracy_record,
    read_accuracy_summary,
    read_cycle,
    read_family,
    read_plan,
    reset_inventory_policy,
    transition_cycle,
)


def test_price_realization_uplift_is_a_share_of_the_cycle_plan_value():
    """The price lever buys no units and costs no hours, so the whole chain hangs
    off a single half-up rounding of a percentage of the cycle's plan value, and
    the resulting closure is small enough to attract the lowest trade rate.

    PRD: "For a price-realization scenario it is the cycle's `plan_value_cents`,
    as it stands at evaluation time, multiplied by `price_increase_pct` divided by
    one hundred, rounded half up to a whole cent."

    Design: Corner/calculations/scenario_price_realization_has_zero_incremental_units_and_zero_investment
    """
    family = create_family()
    item = create_item(family["id"], unit_price_cents=1001)
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=14)
    cycle = create_cycle(cycle_code="CY-PRICE", financial_commitment_cents=0)
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["constrained_units"] == 1330
    transition_cycle(cycle["id"], "SCENARIO_REVIEW")
    assert read_cycle(cycle["id"])["plan_value_cents"] == 1331330

    scenario = create_price_scenario(cycle["id"], 5, name="List price +5")
    evaluated = evaluate_scenario(scenario["id"])
    assert_scenario(evaluated)
    assert evaluated["status"] == "EVALUATED"
    assert evaluated["incremental_units"] == 0
    assert evaluated["investment_cost_cents"] == 0
    assert evaluated["target_item_id"] is None
    assert evaluated["added_capacity_hours"] is None
    assert evaluated["gross_uplift_cents"] == 66567
    assert evaluated["gross_uplift_cents"] != 66566
    assert evaluated["pre_trade_closure_cents"] == 66567
    assert float(evaluated["trade_rate_pct"]) == 4.0
    assert evaluated["trade_spend_cents"] == 2663
    assert evaluated["net_gap_closure_cents"] == 63904
    assert_scenario_closure_chain(evaluated)


def test_a_pre_trade_closure_of_exactly_fifty_thousand_dollars_pays_the_top_rate():
    """The band floors are inclusive, so one extra purchased hour tips the closure
    onto the top tier and the higher rate applied to the gross uplift leaves the
    larger investment closing less gap than the smaller one.

    PRD: "Three bands are tested in order, first match winning: a pre-trade
    closure of at least 5,000,000 cents (50,000 dollars) attracts a rate of 8.0;
    failing that, at least 1,000,000 cents (10,000 dollars) attracts 6.0; anything
    below that attracts 4.0."

    Design: Corner/calculations/scenario_trade_tier_at_5_000_000_boundary_selects_eight_percent
    """
    family = create_family()
    item = create_item(family["id"], unit_price_cents=750)
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=10)
    cycle = create_cycle(cycle_code="CY-TIER", financial_commitment_cents=0)
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=20000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")

    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["gross_requirement_units"] == 20000
    assert plan["demand_side_units"] == 20330
    assert plan["available_units"] == 1000
    assert plan["constrained_units"] == 1000
    assert plan["shortfall_units"] == 19330
    assert plan["constraint_type"] == "CAPACITY"
    transition_cycle(cycle["id"], "SCENARIO_REVIEW")
    assert read_cycle(cycle["id"])["plan_value_cents"] == 750000

    big = create_capacity_scenario(cycle["id"], item["id"], 100, name="Buy 100 hours")
    small = create_capacity_scenario(cycle["id"], item["id"], 99, name="Buy 99 hours")

    big = evaluate_scenario(big["id"])
    assert big["incremental_units"] == 10000
    assert big["gross_uplift_cents"] == 7500000
    assert big["investment_cost_cents"] == 2500000
    assert big["pre_trade_closure_cents"] == 5000000
    assert float(big["trade_rate_pct"]) == 8.0
    assert big["trade_spend_cents"] == 600000
    assert big["net_gap_closure_cents"] == 4400000

    small = evaluate_scenario(small["id"])
    assert small["incremental_units"] == 9900
    assert small["gross_uplift_cents"] == 7425000
    assert small["investment_cost_cents"] == 2475000
    assert small["pre_trade_closure_cents"] == 4950000
    assert float(small["trade_rate_pct"]) == 6.0
    assert small["trade_spend_cents"] == 445500
    assert small["net_gap_closure_cents"] == 4504500

    assert small["net_gap_closure_cents"] > big["net_gap_closure_cents"]
    assert big["status"] == "EVALUATED"
    assert small["status"] == "EVALUATED"
    assert read_cycle(cycle["id"])["selected_closure_cents"] == 0


def test_a_stale_plan_drops_out_of_the_plan_value_without_being_rewritten():
    """The roll-up filters the plan out by status rather than zeroing it, so the
    plan keeps its own constrained quantity while the cycle's value collapses back
    to nothing and the whole commitment reappears as the gap.

    PRD: "`plan_value_cents` is the sum, over the cycle's supply plans whose
    status is `PLANNED`, `RATIONED` or `COMMITTED`, of each plan's
    `constrained_units` multiplied by that plan's item's `unit_price_cents`; plans
    in `STALE` are excluded."

    Design: Corner/calculations/cycle_financials_excludes_stale_supply_plan_from_plan_value
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code="CY-STALE", financial_commitment_cents=2000000)
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    plan = build_supply_plan(cycle["id"], item["id"])

    assert plan["status"] == "PLANNED"
    assert plan["constrained_units"] == 900
    assert plan["constraint_type"] == "CAPACITY"
    before = read_cycle(cycle["id"])
    assert before["plan_value_cents"] == 900000
    assert before["gross_gap_cents"] == 1100000
    assert before["selected_closure_cents"] == 0
    assert before["residual_gap_cents"] == 1100000
    assert before["constrained_plan_count"] == 1
    assert before["posture"] == "AT_RISK"

    reset = reset_inventory_policy(item["id"], 99.0, 0.50, 60)
    assert reset["safety_stock_units"] == 1648
    assert reset["reorder_point_units"] == 3648

    stale = read_plan(plan["id"])
    assert stale["status"] == "STALE"
    assert stale["requires_replan"] is True
    assert stale["constrained_units"] == 900
    assert stale["constraint_type"] == "CAPACITY"

    after = read_cycle(cycle["id"])
    assert after["plan_value_cents"] == 0
    assert after["gross_gap_cents"] == 2000000
    assert after["residual_gap_cents"] == 2000000
    assert after["constrained_plan_count"] == 0
    assert after["posture"] == "AT_RISK"
    assert_cycle_money_conserved(after)
    assert_cycle_posture(after)


def test_one_constrained_plan_drags_an_overcovered_cycle_to_at_risk():
    """The risk test is a disjunction, so adding a capacity-starved plan flips the
    posture even though it pushes the residual gap further below zero.

    PRD: "if the cycle's `status` is `PUBLISHED`, posture is `FROZEN`; otherwise,
    if the cycle's `residual_gap_cents` is greater than zero **or** its
    `constrained_plan_count` is at least 1, posture is `AT_RISK`; otherwise
    posture is `GREEN`."

    Design: Corner/calculations/cycle_posture_green_only_when_gap_closed_and_no_constrained_plan
    """
    roomy = create_family()
    tight = create_family(
        family_code="FAM-TIGHT",
        name="Tight Family",
        accountable_planner_user_id="planner-2",
    )
    roomy_item = create_item(roomy["id"], sku="SKU-BASE")
    tight_item = create_item(tight["id"], sku="SKU-TIGHT")
    customer = create_customer()
    create_capacity_block(roomy["id"], available_hours=14)
    create_capacity_block(tight["id"], available_hours=2)
    cycle = create_cycle(cycle_code="CY-POSTURE", financial_commitment_cents=0)
    create_forecast(cycle["id"], roomy_item["id"], customer["id"], level_units=1000)
    create_forecast(cycle["id"], tight_item["id"], customer["id"], level_units=1000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")

    roomy_plan = build_supply_plan(cycle["id"], roomy_item["id"])
    assert roomy_plan["available_units"] == 1400
    assert roomy_plan["demand_side_units"] == 1330
    assert roomy_plan["constrained_units"] == 1330
    assert roomy_plan["shortfall_units"] == 0
    assert roomy_plan["constraint_type"] == "NONE"

    green = read_cycle(cycle["id"], EXEC)
    assert green["plan_value_cents"] == 1330000
    assert green["gross_gap_cents"] == -1330000
    assert green["residual_gap_cents"] == -1330000
    assert green["constrained_plan_count"] == 0
    assert green["posture"] == "GREEN"

    tight_plan = build_supply_plan(cycle["id"], tight_item["id"])
    assert tight_plan["available_units"] == 200
    assert tight_plan["demand_side_units"] == 1330
    assert tight_plan["constrained_units"] == 200
    assert tight_plan["shortfall_units"] == 1130
    assert tight_plan["constraint_type"] == "CAPACITY"

    at_risk = read_cycle(cycle["id"], EXEC)
    assert at_risk["plan_value_cents"] == 1530000
    assert at_risk["gross_gap_cents"] == -1530000
    assert at_risk["residual_gap_cents"] == -1530000
    assert at_risk["constrained_plan_count"] == 1
    assert at_risk["posture"] == "AT_RISK"
    assert at_risk["residual_gap_cents"] < green["residual_gap_cents"]
    assert_cycle_posture(at_risk)


def test_a_zero_actual_line_has_no_percentage_error_but_still_counts():
    """With nothing shipped the percentage error is undefined, and because the
    weighted metric divides by the same zero total the whole grade collapses to
    ungraded while the record itself is still counted.

    PRD: "`ape_pct` is `abs_error_units` divided by `actual_units`, expressed as a
    percentage and rounded half up to two decimal places — except that when
    `actual_units` is 0 the ratio is undefined and `ape_pct` is null."

    Design: Corner/calculations/accuracy_record_ape_pct_is_null_when_actual_units_zero
    """
    family = create_family()
    item = create_item_with_defaults(family["id"], lifecycle_state="MATURE")
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-ZERO", financial_commitment_cents=0)
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=500)
    advance_cycle_to(cycle["id"], "PUBLISHED")

    record = post_accuracy_record(cycle["id"], item["id"], customer["id"], 0)
    assert_accuracy_record(record)
    assert record["forecast_units_snapshot"] == 500
    assert record["signed_error_units"] == 500
    assert record["abs_error_units"] == 500
    assert record["ape_pct"] is None
    assert record["accountable_planner_user_id"] == "planner-1"

    summary = read_accuracy_summary(cycle["id"], EXEC)
    assert_accuracy_summary(summary)
    assert summary["record_count"] == 1
    assert summary["total_actual_units"] == 0
    assert summary["total_abs_error_units"] == 500
    assert summary["mape_pct"] is None
    assert summary["wmape_pct"] is None
    assert summary["bias_pct"] is None
    assert summary["bias_flag"] == "NONE"
    assert summary["accuracy_grade"] == "UNGRADED"
    assert summary["worst_item_id"] == item["id"]

    rolled = read_family(family["id"])
    assert rolled["scored_record_count"] == 1
    assert rolled["rolling_wmape_pct"] is None
    assert rolled["rolling_bias_pct"] is None


def test_a_bias_of_exactly_minus_five_flags_while_minus_four_point_nine_does_not():
    """The band is inclusive at the negative threshold, so a single unit of
    forecast separates a flagged family from an unflagged one, and both still earn
    the top grade because the grade reads the weighted error instead of the bias.

    PRD: "a bias of -5.00 or lower means systematic under-forecasting and the flag
    is `UNDER_FORECAST`; anything strictly between those two bounds, and any null
    bias, gives a flag of `NONE`."

    Design: Corner/calculations/accuracy_rollup_bias_flag_under_forecast_at_negative_threshold
    """
    family_a = create_family(
        family_code="FAM-A", name="Family A", accountable_planner_user_id="planner-a"
    )
    family_b = create_family(
        family_code="FAM-B", name="Family B", accountable_planner_user_id="planner-b"
    )
    item_a = create_item_with_defaults(family_a["id"], sku="SKU-A")
    item_b = create_item_with_defaults(family_b["id"], sku="SKU-B")
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-BIAS", financial_commitment_cents=0)
    create_forecast(cycle["id"], item_a["id"], customer["id"], level_units=950)
    create_forecast(cycle["id"], item_b["id"], customer["id"], level_units=951)
    advance_cycle_to(cycle["id"], "PUBLISHED")

    record_a = post_accuracy_record(cycle["id"], item_a["id"], customer["id"], 1000)
    assert record_a["forecast_units_snapshot"] == 950
    assert record_a["signed_error_units"] == -50
    assert record_a["abs_error_units"] == 50
    assert float(record_a["ape_pct"]) == 5.00
    assert record_a["accountable_planner_user_id"] == "planner-a"

    record_b = post_accuracy_record(cycle["id"], item_b["id"], customer["id"], 1000)
    assert record_b["forecast_units_snapshot"] == 951
    assert record_b["signed_error_units"] == -49
    assert record_b["abs_error_units"] == 49
    assert float(record_b["ape_pct"]) == 4.90
    assert record_b["accountable_planner_user_id"] == "planner-b"

    rolled_a = read_family(family_a["id"])
    assert float(rolled_a["rolling_wmape_pct"]) == 5.00
    assert float(rolled_a["rolling_bias_pct"]) == -5.00
    assert rolled_a["bias_flag"] == "UNDER_FORECAST"
    assert rolled_a["accuracy_grade"] == "A"
    assert rolled_a["scored_record_count"] == 1

    rolled_b = read_family(family_b["id"])
    assert float(rolled_b["rolling_wmape_pct"]) == 4.90
    assert float(rolled_b["rolling_bias_pct"]) == -4.90
    assert rolled_b["bias_flag"] == "NONE"
    assert rolled_b["accuracy_grade"] == "A"
    assert rolled_b["scored_record_count"] == 1

    assert rolled_a["bias_flag"] != "OVER_FORECAST"
    assert rolled_b["bias_flag"] != "OVER_FORECAST"


def test_the_cycle_summary_and_the_family_rollup_read_different_record_sets():
    """Two records of wildly different volume live in two different cycles, so the
    per-cycle read sees one of them while the family fields weight both together —
    and every figure the two scopes report differs.

    PRD: "the family's own `rolling_wmape_pct`, `rolling_bias_pct`, `bias_flag`,
    `accuracy_grade` and `scored_record_count` roll up **every** accuracy record
    whose item belongs to that family, across **all** cycles, whereas the cycle
    accuracy summary read described below rolls up only the records whose
    `cycle_id` is the cycle in its path"

    Design: Corner/calculations/accuracy_summary_scope_is_cycle_while_family_rollup_spans_all_cycles
    """
    family = create_family()
    item = create_item_with_defaults(family["id"], lifecycle_state="MATURE")
    customer = create_customer()
    cycle_a = create_cycle(cycle_code="CY-A", financial_commitment_cents=0)
    cycle_b = create_cycle(cycle_code="CY-B", financial_commitment_cents=0)
    create_forecast(cycle_a["id"], item["id"], customer["id"], level_units=130)
    create_forecast(cycle_b["id"], item["id"], customer["id"], level_units=5200)
    advance_cycle_to(cycle_a["id"], "PUBLISHED")
    advance_cycle_to(cycle_b["id"], "PUBLISHED")

    record_a = post_accuracy_record(cycle_a["id"], item["id"], customer["id"], 100)
    assert record_a["forecast_units_snapshot"] == 130
    assert record_a["signed_error_units"] == 30
    assert record_a["abs_error_units"] == 30
    assert float(record_a["ape_pct"]) == 30.00

    record_b = post_accuracy_record(cycle_b["id"], item["id"], customer["id"], 5000)
    assert record_b["forecast_units_snapshot"] == 5200
    assert record_b["signed_error_units"] == 200
    assert record_b["abs_error_units"] == 200
    assert float(record_b["ape_pct"]) == 4.00

    summary_a = read_accuracy_summary(cycle_a["id"], EXEC)
    assert summary_a["record_count"] == 1
    assert float(summary_a["mape_pct"]) == 30.00
    assert float(summary_a["wmape_pct"]) == 30.00
    assert float(summary_a["bias_pct"]) == 30.00
    assert summary_a["bias_flag"] == "OVER_FORECAST"
    assert summary_a["accuracy_grade"] == "C"
    assert summary_a["total_actual_units"] == 100
    assert summary_a["total_abs_error_units"] == 30

    summary_b = read_accuracy_summary(cycle_b["id"], EXEC)
    assert summary_b["record_count"] == 1
    assert float(summary_b["mape_pct"]) == 4.00
    assert float(summary_b["wmape_pct"]) == 4.00
    assert summary_b["accuracy_grade"] == "A"

    rolled = read_family(family["id"], EXEC)
    assert rolled["scored_record_count"] == 2
    assert float(rolled["rolling_wmape_pct"]) == 4.51
    assert float(rolled["rolling_bias_pct"]) == 4.51
    assert rolled["bias_flag"] == "NONE"
    assert rolled["accuracy_grade"] == "A"
    assert float(rolled["rolling_wmape_pct"]) != float(summary_a["wmape_pct"])
