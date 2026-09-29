"""Breadth over the endpoint surface itself: what a non-creating POST returns and
how often it moves a row's counter, what a computed read reports and how a query
filter re-scopes it, and which calls are inert on the rows they merely consult.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_accuracy_summary,
    assert_item,
    assert_scenario,
    assert_scenario_closure_chain,
    assert_supply_plan,
)
from test_helpers.factories import inventory_policy_payload
from test_helpers.fixtures import (
    EXEC,
    LEAD,
    SUPPLY,
    advance_cycle_to,
    build_supply_plan,
    create_capacity_block,
    create_capacity_scenario,
    create_customer,
    create_cycle,
    create_family,
    create_forecast,
    create_item,
    create_promotion,
    evaluate_scenario,
    post_accuracy_record,
    read_accuracy_summary,
    read_cycle,
    read_item,
    read_plan,
    read_promotion,
    set_clock,
    transition_cycle,
)


def test_the_policy_reset_answers_with_the_whole_item_and_moves_the_counter_once():
    """The reset is not a creation, so it answers 200 with the full item rather than
    a policy fragment, and each call — including a resubmission of the identical
    triple — advances the row's counter by exactly one.

    PRD: "a counter that starts at 1 on creation and increases by exactly 1 on every
    mutation of the row."

    Design: Corner/endpoints/inventory_policy_reset_returns_200_item_and_bumps_version_once
    """
    family = create_family()
    item = create_item(family["id"])
    assert item["safety_stock_units"] == 330
    assert item["reorder_point_units"] == 1330

    payload = inventory_policy_payload(97.5, 0.20, 30)
    first = validate_success(
        api_client.reset_inventory_policy(item["id"], payload, SUPPLY), 200
    )
    assert_item(first)
    assert first["id"] == item["id"]
    assert first["sku"] == item["sku"]
    assert first["family_id"] == family["id"]
    assert first["unit_price_cents"] == 1000
    assert first["safety_stock_units"] == 392
    assert first["reorder_point_units"] == 1392
    assert first["version"] == item["version"] + 1

    second = validate_success(
        api_client.reset_inventory_policy(item["id"], payload, SUPPLY), 200
    )
    assert second["safety_stock_units"] == 392
    assert second["reorder_point_units"] == 1392
    assert second["version"] == first["version"] + 1

    reread = read_item(item["id"])
    assert reread["version"] == second["version"]
    assert reread["avg_monthly_demand_units"] == 1000
    assert reread["unit_price_cents"] == 1000
    assert float(reread["service_level_target_pct"]) == 97.5


def test_the_worst_offender_is_the_high_ratio_item_not_the_high_volume_one():
    """A tiny item with a large proportional miss beats a huge item with a larger
    absolute miss, and narrowing the read to one family re-scopes every figure it
    reports — including which item is named as the offender.

    PRD: "**The worst offender** is identified by computing, for each distinct item
    in the record set, that item's own volume-weighted error — the sum of its
    records' `abs_error_units` divided by the sum of its records' `actual_units` —
    and taking the item with the highest such ratio."

    Design: Corner/endpoints/accuracy_summary_worst_item_and_family_filter_narrow_the_record_set
    """
    family_small = create_family(
        family_code="FAM-SMALL",
        name="Small Family",
        accountable_planner_user_id="planner-s",
    )
    family_big = create_family(
        family_code="FAM-BIG",
        name="Big Family",
        accountable_planner_user_id="planner-b",
    )
    item_small = create_item(
        family_small["id"], sku="SKU-SMALL", avg_monthly_demand_units=130
    )
    item_big = create_item(
        family_big["id"], sku="SKU-BIG", avg_monthly_demand_units=5200
    )
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-SUMMARY", financial_commitment_cents=0)
    create_forecast(cycle["id"], item_small["id"], customer["id"], level_units=130)
    create_forecast(cycle["id"], item_big["id"], customer["id"], level_units=5200)
    advance_cycle_to(cycle["id"], "PUBLISHED")

    small_record = post_accuracy_record(
        cycle["id"], item_small["id"], customer["id"], 100
    )
    assert small_record["abs_error_units"] == 30
    assert float(small_record["ape_pct"]) == 30.00

    big_record = post_accuracy_record(cycle["id"], item_big["id"], customer["id"], 5000)
    assert big_record["abs_error_units"] == 200
    assert float(big_record["ape_pct"]) == 4.00

    everything = read_accuracy_summary(cycle["id"], EXEC)
    assert_accuracy_summary(everything)
    assert everything["record_count"] == 2
    assert everything["total_actual_units"] == 5100
    assert everything["total_abs_error_units"] == 230
    assert float(everything["mape_pct"]) == 17.00
    assert float(everything["wmape_pct"]) == 4.51
    assert float(everything["bias_pct"]) == 4.51
    assert everything["bias_flag"] == "NONE"
    assert everything["accuracy_grade"] == "A"
    assert everything["accuracy_grade"] != "B"
    assert everything["worst_item_id"] == item_small["id"]
    assert everything["worst_item_id"] != item_big["id"]

    big_only = read_accuracy_summary(cycle["id"], EXEC, params={"family_id": family_big["id"]})
    assert big_only["record_count"] == 1
    assert big_only["total_actual_units"] == 5000
    assert big_only["total_abs_error_units"] == 200
    assert float(big_only["mape_pct"]) == 4.00
    assert float(big_only["wmape_pct"]) == 4.00
    assert big_only["bias_flag"] == "NONE"
    assert big_only["accuracy_grade"] == "A"
    assert big_only["worst_item_id"] == item_big["id"]

    small_only = read_accuracy_summary(
        cycle["id"], EXEC, params={"family_id": family_small["id"]}
    )
    assert small_only["record_count"] == 1
    assert small_only["total_actual_units"] == 100
    assert small_only["total_abs_error_units"] == 30
    assert float(small_only["mape_pct"]) == 30.00
    assert float(small_only["wmape_pct"]) == 30.00
    assert float(small_only["bias_pct"]) == 30.00
    assert small_only["bias_flag"] == "OVER_FORECAST"
    assert small_only["accuracy_grade"] == "C"
    assert small_only["worst_item_id"] == item_small["id"]

    assert big_only["total_actual_units"] + small_only["total_actual_units"] == 5100
    assert (
        big_only["total_abs_error_units"] + small_only["total_abs_error_units"] == 230
    )


def test_winding_the_clock_back_reopens_a_promotion_window_it_had_closed():
    """The clock capability is the only thing standing between a refused approval and
    an accepted one: the same draft, the same reviewer and the same window succeed
    once the instant is moved back, and the refused attempt left the row alone.

    PRD: "An `SopAdmin` capability repositions the clock to a supplied `to_iso8601`
    instant and echoes the new setting back as `current_utc`; repositioning the clock
    modifies no business rows."

    Design: Corner/endpoints/clock_moves_backward_and_reopens_a_frozen_promotion_horizon
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    promotion = create_promotion(
        item["id"],
        customer["id"],
        start_month="2026-09",
        end_month="2026-09",
        lift_pct=10,
        cannibalization_pct=2,
    )
    assert promotion["status"] == "DRAFT"

    forward = set_clock("2026-09-15T00:00:00Z")
    assert forward["current_utc"].startswith("2026-09-15T00:00:00")

    frozen = validate_error(
        api_client.approve_promotion(promotion["id"], LEAD, {}),
        ApiErrorId.ERR_PROMOTION_HORIZON_FROZEN.value,
        422,
    )
    assert frozen["error_id"] != ApiErrorId.ERR_ITEM_NOT_PROMOTABLE.value

    untouched = read_promotion(promotion["id"])
    assert untouched["status"] == "DRAFT"
    assert untouched["version"] == promotion["version"]
    assert untouched["start_month"] == "2026-09"

    backward = set_clock("2026-08-01T00:00:00Z")
    assert backward["current_utc"].startswith("2026-08-01T00:00:00")

    approved = validate_success(api_client.approve_promotion(promotion["id"], LEAD, {}), 200)
    assert approved["status"] == "APPROVED"
    assert approved["version"] == promotion["version"] + 1

    rows, meta = validate_paginated(
        api_client.list_promotions(LEAD, params={"status": "APPROVED", "limit": 100})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == promotion["id"]


def test_the_constraint_filter_partitions_the_cycle_into_its_three_binding_reasons():
    """Three items differ only in what limits them — nothing, machine hours and
    components — so the same list read returns all three unfiltered and exactly one
    per constraint value, while a constraint nobody hit returns nothing.

    PRD: "Plans are readable individually and as a list filtered by `cycle_id`,
    `item_id`, `status` and `constraint_type`."

    Design: Corner/endpoints/list_supply_plans_filter_by_constraint_type_narrows_result_set
    """
    family_a = create_family(
        family_code="FAM-A", name="Family A", accountable_planner_user_id="planner-a"
    )
    family_b = create_family(
        family_code="FAM-B", name="Family B", accountable_planner_user_id="planner-b"
    )
    family_c = create_family(
        family_code="FAM-C", name="Family C", accountable_planner_user_id="planner-c"
    )
    item_a = create_item(family_a["id"], sku="SKU-A")
    item_b = create_item(family_b["id"], sku="SKU-B")
    item_c = create_item(family_c["id"], sku="SKU-C", material_supply_cap_units=500)
    customer = create_customer()
    create_capacity_block(family_a["id"], available_hours=14)
    create_capacity_block(family_b["id"], available_hours=9)
    create_capacity_block(family_c["id"], available_hours=20)
    cycle = create_cycle(cycle_code="CY-FILTER", financial_commitment_cents=0)
    for item in (item_a, item_b, item_c):
        create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")

    plan_a = build_supply_plan(cycle["id"], item_a["id"])
    assert_supply_plan(plan_a)
    assert plan_a["demand_side_units"] == 1330
    assert plan_a["available_units"] == 1400
    assert plan_a["constrained_units"] == 1330
    assert plan_a["shortfall_units"] == 0
    assert plan_a["constraint_type"] == "NONE"

    plan_b = build_supply_plan(cycle["id"], item_b["id"])
    assert plan_b["available_units"] == 900
    assert plan_b["constrained_units"] == 900
    assert plan_b["shortfall_units"] == 430
    assert plan_b["constraint_type"] == "CAPACITY"

    plan_c = build_supply_plan(cycle["id"], item_c["id"])
    assert plan_c["available_units"] == 2000
    assert plan_c["material_cap_units"] == 500
    assert plan_c["constrained_units"] == 500
    assert plan_c["shortfall_units"] == 830
    assert plan_c["constraint_type"] == "MATERIAL"

    everything, everything_meta = validate_paginated(
        api_client.list_supply_plans(SUPPLY, params={"cycle_id": cycle["id"], "limit": 100})
    )
    assert everything_meta["total_count"] == 3
    assert len(everything) == 3

    for constraint, expected in (
        ("NONE", plan_a),
        ("CAPACITY", plan_b),
        ("MATERIAL", plan_c),
    ):
        rows, meta = validate_paginated(
            api_client.list_supply_plans(
                SUPPLY,
                params={
                    "cycle_id": cycle["id"],
                    "constraint_type": constraint,
                    "limit": 100,
                },
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == expected["id"]
        assert rows[0]["constraint_type"] == constraint

    empty, empty_meta = validate_paginated(
        api_client.list_supply_plans(
            SUPPLY,
            params={
                "cycle_id": cycle["id"],
                "constraint_type": "INVENTORY_TARGET",
                "limit": 100,
            },
        )
    )
    assert empty_meta["total_count"] == 0
    assert empty == []

    stale, stale_meta = validate_paginated(
        api_client.list_supply_plans(
            SUPPLY, params={"cycle_id": cycle["id"], "status": "STALE", "limit": 100}
        )
    )
    assert stale_meta["total_count"] == 0
    assert stale == []

    rolled = read_cycle(cycle["id"])
    assert rolled["plan_value_cents"] == 2730000
    assert rolled["constrained_plan_count"] == 2


def test_an_evaluation_writes_seven_figures_onto_the_scenario_and_nothing_elsewhere():
    """Evaluation is absent from the list of events that recompute a cycle's money, so
    all five cycle figures, the cycle's own counter and the target plan come out of the
    call byte for byte as they went in.

    PRD: "Five events trigger it — every cycle phase transition, the creation of a
    supply plan, a plan going `STALE` from either `PLANNED` or `RATIONED`, a scenario
    being selected, and a scenario being superseded — and it always recomputes all five
    figures from scratch."

    Design: Corner/endpoints/scenario_evaluate_writes_only_the_scenario_and_leaves_cycle_money_untouched
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code="CY-INERT", financial_commitment_cents=2000000)
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")
    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["constrained_units"] == 900
    assert plan["shortfall_units"] == 430
    transition_cycle(cycle["id"], "SCENARIO_REVIEW")

    scenario = create_capacity_scenario(
        cycle["id"], item["id"], 5, name="Five bought hours"
    )
    assert scenario["status"] == "DRAFT"

    before = read_cycle(cycle["id"], EXEC)
    assert before["plan_value_cents"] == 900000
    assert before["gross_gap_cents"] == 1100000
    assert before["selected_closure_cents"] == 0
    assert before["residual_gap_cents"] == 1100000
    assert before["constrained_plan_count"] == 1
    assert before["posture"] == "AT_RISK"

    evaluated = evaluate_scenario(scenario["id"])
    assert_scenario(evaluated)
    assert evaluated["status"] == "EVALUATED"
    assert evaluated["incremental_units"] == 430
    assert evaluated["gross_uplift_cents"] == 430000
    assert evaluated["investment_cost_cents"] == 125000
    assert evaluated["pre_trade_closure_cents"] == 305000
    assert float(evaluated["trade_rate_pct"]) == 4.0
    assert evaluated["trade_spend_cents"] == 17200
    assert evaluated["net_gap_closure_cents"] == 287800
    assert_scenario_closure_chain(evaluated)

    after = read_cycle(cycle["id"], EXEC)
    assert after["plan_value_cents"] == before["plan_value_cents"]
    assert after["gross_gap_cents"] == before["gross_gap_cents"]
    assert after["selected_closure_cents"] == 0
    assert after["selected_closure_cents"] != 287800
    assert after["residual_gap_cents"] == 1100000
    assert after["residual_gap_cents"] != 812200
    assert after["constrained_plan_count"] == 1
    assert after["posture"] == "AT_RISK"
    assert after["version"] == before["version"]

    unmoved = read_plan(plan["id"])
    assert unmoved["status"] == "PLANNED"
    assert unmoved["constrained_units"] == 900
    assert unmoved["requires_replan"] is False
