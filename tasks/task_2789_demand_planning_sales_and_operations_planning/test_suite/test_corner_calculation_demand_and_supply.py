"""Arithmetic breadth on the demand and supply side: which baseline variant is
selected and which terms survive it, the derived inventory policy, the input sets
that feed a plan's requirement and capacity, and the rationing waterfall's passes.
"""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import api_client
from test_helpers.assertions import (
    assert_allocation,
    assert_allocation_units_conserved,
    assert_demand_forecast,
    assert_item,
    assert_supply_plan,
)
from test_helpers.fixtures import (
    SUPPLY,
    build_supply_plan,
    create_capacity_block,
    create_customer,
    create_cycle,
    create_family,
    create_forecast,
    create_item,
    list_plan_allocations,
    lock_forecast_directly,
    ration_plan,
    read_cycle,
    read_plan,
    reset_inventory_policy,
    transition_cycle,
)


def test_smoothed_baseline_carries_the_trend_across_two_horizon_months():
    """The trend is multiplied by the zero-based month offset, the whole sum is
    seasonalised and only then does the causal uplift close the calculation.

    PRD: "It is the difference in years between the forecast `month` and
    `horizon_start_month` multiplied by twelve, plus the difference in month
    numbers between the two."

    Design: Corner/calculations/baseline_holt_winters_applies_trend_and_seasonality_at_offset_two
    """
    family = create_family()
    item = create_item(family["id"], demand_cv=0.20)
    customer = create_customer()
    cycle = create_cycle(
        cycle_code="CY-HW",
        horizon_start_month="2026-09",
        horizon_end_month="2026-11",
        financial_commitment_cents=0,
    )

    line = create_forecast(
        cycle["id"],
        item["id"],
        customer["id"],
        month="2026-11",
        level_units=800,
        trend_units_per_month=25,
        seasonal_index=1.50,
        causal_uplift_pct=20,
    )
    assert_demand_forecast(line)
    assert line["method"] == "HOLT_WINTERS"
    assert line["baseline_units"] == 1530
    assert line["baseline_units"] != 1485
    assert line["baseline_units"] != 1440
    assert line["baseline_units"] != 1275
    assert line["consensus_units"] == 1530
    assert line["endorsed_adjustment_count"] == 0
    assert line["status"] == "BASELINE"


def test_prelaunch_baseline_scales_by_the_ramp_and_drops_the_trend():
    """A new product takes the analogue variant even though its variability would
    otherwise select the intermittent one, and that variant keeps seasonality
    while suppressing the trend entirely.

    PRD: "Under `ANALOG_PROFILE`, trend alone is suppressed and the level is
    scaled by the item's ramp factor: the raw level is `level_units` multiplied by
    `npi_ramp_pct` divided by one hundred, and that product is then multiplied by
    `seasonal_index`."

    Design: Corner/calculations/baseline_analog_profile_scales_by_npi_ramp_and_ignores_trend
    """
    family = create_family()
    item = create_item(
        family["id"],
        sku="SKU-NPI",
        npi_ramp_pct=60,
        demand_cv=0.90,
        lifecycle_state="PRELAUNCH",
    )
    customer = create_customer()
    cycle = create_cycle(
        cycle_code="CY-ANALOG",
        horizon_start_month="2026-09",
        horizon_end_month="2026-11",
        financial_commitment_cents=0,
    )

    line = create_forecast(
        cycle["id"],
        item["id"],
        customer["id"],
        month="2026-11",
        level_units=1000,
        trend_units_per_month=25,
        seasonal_index=1.20,
        causal_uplift_pct=10,
    )
    assert line["method"] == "ANALOG_PROFILE"
    assert line["method"] != "CROSTON_FLAT"
    assert line["baseline_units"] == 792
    assert line["baseline_units"] != 832
    assert line["baseline_units"] != 1100
    assert line["consensus_units"] == 792


def test_service_level_target_exactly_on_a_tier_edge_takes_the_higher_factor():
    """The safety-factor table is tested downwards with inclusive band floors, so
    a target sitting exactly on the edge takes the stronger factor while one a
    tenth below it falls through to the band underneath.

    PRD: "testing the bands in descending order and taking the first that
    matches: a target of 99.0 percent or higher uses a factor of 2.33; failing
    that, 97.5 percent or higher uses 1.96; failing that, 95.0 percent or higher
    uses 1.65"

    Design: Corner/calculations/inventory_policy_z_tier_at_97_5_boundary
    """
    family = create_family()

    at_edge = create_item(
        family["id"], sku="SKU-AT", service_level_target_pct=97.5, demand_cv=0.20
    )
    assert_item(at_edge)
    assert at_edge["safety_stock_units"] == 392
    assert at_edge["reorder_point_units"] == 1392
    assert at_edge["lifecycle_state"] == "MATURE"
    assert at_edge["family_id"] == family["id"]

    below_edge = create_item(
        family["id"], sku="SKU-UNDER", service_level_target_pct=97.4, demand_cv=0.20
    )
    assert below_edge["safety_stock_units"] == 330
    assert below_edge["reorder_point_units"] == 1330
    assert below_edge["lifecycle_state"] == "MATURE"
    assert below_edge["family_id"] == family["id"]


def test_reorder_point_ceilings_the_cycle_stock_term_on_its_own():
    """With a lead time that is not a whole number of months both terms carry a
    fraction, and ceilinging them separately lands one unit above what a single
    ceiling over the sum would produce.

    PRD: "the cycle-stock term, `avg_monthly_demand_units` multiplied by
    `lead_time_days` and divided by thirty, is ceilinged to an integer **first**,
    and the already-ceilinged `safety_stock_units` is then added to it."

    Design: Corner/calculations/reorder_point_ceils_cycle_stock_before_adding_safety_stock
    """
    family = create_family()
    item = create_item(family["id"])
    assert item["safety_stock_units"] == 330
    assert item["reorder_point_units"] == 1330

    reset = reset_inventory_policy(item["id"], 95.0, 0.20, 31)
    assert reset["safety_stock_units"] == 336
    assert reset["reorder_point_units"] == 1370
    assert reset["reorder_point_units"] != 1369
    assert reset["lead_time_days"] == 31
    assert reset["version"] == item["version"] + 1


def test_gross_requirement_is_keyed_on_the_cycle_and_the_item_together():
    """Three locked lines exist, but only the one matching both the plan's cycle
    and its item enters the requirement — the sibling item's line and the other
    cycle's line for the same item are both out of scope.

    PRD: "`gross_requirement_units` is the sum of `consensus_units` over the
    cycle's forecast lines for that item whose status is `CONSENSUS_LOCKED`, taken
    across every customer and every horizon month."

    Design: Corner/calculations/gross_requirement_excludes_other_cycles_and_other_items
    """
    family = create_family()
    item_one = create_item(family["id"], sku="SKU-ONE")
    item_two = create_item(family["id"], sku="SKU-TWO")
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=20)
    cycle_a = create_cycle(cycle_code="CY-A", financial_commitment_cents=0)
    cycle_b = create_cycle(cycle_code="CY-B", financial_commitment_cents=0)

    create_forecast(cycle_a["id"], item_one["id"], customer["id"], level_units=1000)
    create_forecast(cycle_a["id"], item_two["id"], customer["id"], level_units=500)
    other_cycle_line = create_forecast(
        cycle_b["id"], item_one["id"], customer["id"], level_units=700
    )
    lock_forecast_directly(other_cycle_line["id"])
    transition_cycle(cycle_a["id"], "SUPPLY_REVIEW")

    plan = build_supply_plan(cycle_a["id"], item_one["id"])
    assert_supply_plan(plan)
    assert plan["gross_requirement_units"] == 1000
    assert plan["gross_requirement_units"] != 1500
    assert plan["gross_requirement_units"] != 1700
    assert plan["gross_requirement_units"] != 2200
    assert plan["target_build_units"] == 330
    assert plan["available_units"] == 2000
    assert plan["material_cap_units"] == 100000
    assert plan["demand_side_units"] == 1330
    assert plan["constrained_units"] == 1330
    assert plan["shortfall_units"] == 0
    assert plan["constraint_type"] == "NONE"

    assert read_cycle(cycle_a["id"])["plan_value_cents"] == 1330000
    assert read_cycle(cycle_b["id"])["plan_value_cents"] == 0


def test_a_block_poking_past_the_horizon_contributes_no_hours_at_all():
    """Two blocks of equal size sit in the month, but the one whose interval runs
    past the horizon window is dropped whole rather than prorated, so only half
    the declared hours reach the capacity figure.

    PRD: "A block that pokes out of either end of the horizon is excluded in its
    entirety; there is no proration of partially overlapping blocks."

    Design: Corner/calculations/available_units_excludes_partially_overlapping_capacity_blocks
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    contained = create_capacity_block(
        family["id"],
        start_date="2026-09-01",
        end_date="2026-09-10",
        available_hours=5,
    )
    spilling = create_capacity_block(
        family["id"],
        start_date="2026-09-25",
        end_date="2026-10-05",
        available_hours=5,
    )
    assert contained["available_hours"] is not None
    assert spilling["end_date"] == "2026-10-05"

    listing = api_client.list_capacity_blocks(SUPPLY, params={"family_id": family["id"]})
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 2
    assert len(rows) == 2

    cycle = create_cycle(cycle_code="CY-PART", financial_commitment_cents=0)
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")

    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["available_units"] == 500
    assert plan["available_units"] != 1000
    assert plan["available_units"] != 800
    assert plan["gross_requirement_units"] == 1000
    assert plan["target_build_units"] == 330
    assert plan["demand_side_units"] == 1330
    assert plan["constrained_units"] == 500
    assert plan["shortfall_units"] == 830
    assert plan["constraint_type"] == "CAPACITY"

    reread = read_cycle(cycle["id"])
    assert reread["plan_value_cents"] == 500000
    assert reread["constrained_plan_count"] == 1


def test_a_customer_on_credit_hold_leaves_the_denominator_to_its_peer_alone():
    """The withheld customer's request neither consumes the remainder nor swells
    the pro-rata denominator, so the one remaining pool member is filled outright
    instead of the two of them splitting the supply evenly.

    PRD: "Every candidate whose `credit_hold` is true receives `allocated_units`
    of 0, an `allocation_status` of `WITHHELD_CREDIT_HOLD`, and an
    `allocation_pass` of `NONE`. Their requests do not consume the remainder and
    do not enter any denominator."

    Design: Corner/calculations/rationing_credit_hold_customer_is_withheld_and_excluded_from_pro_rata
    """
    family = create_family()
    item = create_item(family["id"])
    held = create_customer(
        customer_code="CUST-HOLD",
        name="Held Grocery",
        channel="GROCERY",
        priority_rank=3,
        credit_hold=True,
    )
    payer = create_customer(
        customer_code="CUST-OK",
        name="Paying Club",
        channel="CLUB",
        priority_rank=4,
    )
    create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code="CY-HOLD", financial_commitment_cents=0)
    create_forecast(cycle["id"], item["id"], held["id"], level_units=500)
    create_forecast(cycle["id"], item["id"], payer["id"], level_units=500)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")

    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["gross_requirement_units"] == 1000
    assert plan["demand_side_units"] == 1330
    assert plan["available_units"] == 900
    assert plan["constrained_units"] == 900
    assert plan["shortfall_units"] == 430
    assert plan["constraint_type"] == "CAPACITY"

    rationed = ration_plan(plan["id"])
    assert rationed["status"] == "RATIONED"
    assert rationed["unallocated_units"] == 400

    rows = list_plan_allocations(plan["id"])
    assert len(rows) == 2
    for row in rows:
        assert_allocation(row)
    by_customer = {row["customer_id"]: row for row in rows}

    held_row = by_customer[held["id"]]
    assert held_row["requested_units"] == 500
    assert held_row["allocated_units"] == 0
    assert held_row["allocation_status"] == "WITHHELD_CREDIT_HOLD"
    assert held_row["allocation_pass"] == "NONE"
    assert float(held_row["fill_rate_pct"]) == 0.00

    payer_row = by_customer[payer["id"]]
    assert payer_row["requested_units"] == 500
    assert payer_row["allocated_units"] == 500
    assert payer_row["allocated_units"] != 450
    assert payer_row["allocation_status"] == "ALLOCATED"
    assert payer_row["allocation_pass"] == "PRO_RATA"
    assert float(payer_row["fill_rate_pct"]) == 100.00

    assert_allocation_units_conserved(read_plan(plan["id"]), rows)


def test_a_protected_account_that_outruns_supply_empties_the_second_pass():
    """The strategic account is capped at whatever remains rather than at what it
    asked for, and the pool member left with nothing still gets an allocated row
    rather than being treated as withheld.

    PRD: "If that total is zero, or if nothing at all remains after pass one, then
    no units are distributed and the remainder is kept intact, but every pool
    member still receives a row with `allocated_units` of 0, an
    `allocation_status` of `ALLOCATED` and an `allocation_pass` of `NONE`, so the
    plan's customer set stays complete."

    Design: Corner/calculations/protected_request_exceeding_supply_leaves_pro_rata_pool_empty
    """
    family = create_family()
    item = create_item(family["id"])
    protected = create_customer(
        customer_code="CUST-PROT",
        name="Protected National",
        channel="GROCERY",
        priority_rank=1,
    )
    pool_member = create_customer(
        customer_code="CUST-POOL",
        name="Pool Club",
        channel="CLUB",
        priority_rank=4,
    )
    create_capacity_block(family["id"], available_hours=9)
    cycle = create_cycle(cycle_code="CY-PROT", financial_commitment_cents=0)
    create_forecast(cycle["id"], item["id"], protected["id"], level_units=1200)
    create_forecast(cycle["id"], item["id"], pool_member["id"], level_units=500)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")

    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["gross_requirement_units"] == 1700
    assert plan["demand_side_units"] == 2030
    assert plan["available_units"] == 900
    assert plan["constrained_units"] == 900
    assert plan["shortfall_units"] == 1130
    assert plan["constraint_type"] == "CAPACITY"

    rationed = ration_plan(plan["id"])
    assert rationed["unallocated_units"] == 0

    rows = list_plan_allocations(plan["id"])
    assert len(rows) == 2
    by_customer = {row["customer_id"]: row for row in rows}

    protected_row = by_customer[protected["id"]]
    assert protected_row["requested_units"] == 1200
    assert protected_row["allocated_units"] == 900
    assert protected_row["allocated_units"] != 1200
    assert protected_row["allocation_pass"] == "PROTECTED"
    assert protected_row["allocation_status"] == "ALLOCATED"
    assert float(protected_row["fill_rate_pct"]) == 75.00

    pool_row = by_customer[pool_member["id"]]
    assert pool_row["requested_units"] == 500
    assert pool_row["allocated_units"] == 0
    assert pool_row["allocation_pass"] == "NONE"
    assert pool_row["allocation_status"] == "ALLOCATED"
    assert pool_row["allocation_status"] != "WITHHELD_CREDIT_HOLD"
    assert float(pool_row["fill_rate_pct"]) == 0.00

    assert_allocation_units_conserved(read_plan(plan["id"]), rows)
