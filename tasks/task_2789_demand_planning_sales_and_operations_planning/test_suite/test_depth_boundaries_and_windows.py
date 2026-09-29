"""Inclusive/exclusive boundaries: the intermittency threshold, the zero-request
fill rate, closed-inclusive promotion months and half-open capacity dates with
their changeover buffer.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_allocation, assert_allocation_units_conserved
from test_helpers.factories import capacity_block_payload
from test_helpers.fixtures import (
    LEAD,
    SUPPLY,
    approve_promotion,
    create_capacity_block,
    create_customer,
    create_cycle,
    create_family,
    create_forecast,
    create_item,
    create_promotion,
    list_plan_allocations,
    read_plan,
    read_promotion,
    setup_five_customer_rationing,
)


def _cv_threshold_fixture():
    """Two otherwise identical items straddling the intermittency threshold at
    0.75 and 0.74, over a horizon whose third month is 2026-11."""
    family = create_family(family_code="FAM-SPICE", name="Spices")
    at_threshold = create_item(
        family["id"],
        sku="SKU-AT-075",
        unit_price_cents=600,
        unit_cost_cents=200,
        demand_cv=0.75,
    )
    below_threshold = create_item(
        family["id"],
        sku="SKU-BELOW-074",
        unit_price_cents=600,
        unit_cost_cents=200,
        demand_cv=0.74,
    )
    customer = create_customer(
        customer_code="CUST-A", name="Alpha Grocery", channel="GROCERY", priority_rank=3
    )
    cycle = create_cycle(
        cycle_code="SOP-CV-Q4",
        horizon_start_month="2026-09",
        horizon_end_month="2026-12",
        financial_commitment_cents=0,
    )
    return {
        "family": family,
        "at_threshold": at_threshold,
        "below_threshold": below_threshold,
        "customer": customer,
        "cycle": cycle,
    }


def _cv_forecast(cycle_id, item_id, customer_id):
    return create_forecast(
        cycle_id,
        item_id,
        customer_id,
        month="2026-11",
        level_units=1000,
        trend_units_per_month=50,
        seasonal_index=1.20,
        causal_uplift_pct=10,
    )


def test_demand_cv_exactly_at_the_threshold_selects_the_flat_method():
    """At the threshold the intermittent method is chosen, which ignores both the
    trend and the seasonal index and carries only the level through the uplift.

    PRD: "A `demand_cv` of exactly 0.75 selects `CROSTON_FLAT`; 0.74 selects
    `HOLT_WINTERS`."

    Design: Difficulty/boundary_precision_check/demand_cv_exactly_at_intermittent_threshold_selects_croston
    """
    ctx = _cv_threshold_fixture()

    line = _cv_forecast(
        ctx["cycle"]["id"], ctx["at_threshold"]["id"], ctx["customer"]["id"]
    )
    assert line["method"] == "CROSTON_FLAT"
    assert line["baseline_units"] == 1100
    assert line["status"] == "BASELINE"
    assert line["consensus_units"] == line["baseline_units"]


def test_demand_cv_one_hundredth_below_the_threshold_keeps_trend_and_seasonality():
    """One hundredth below the threshold the smoothing method applies, so the
    trend for the horizon offset and the seasonal index both land in the baseline.

    PRD: "Under `HOLT_WINTERS`, both trend and seasonality participate: the raw
    level is `level_units` plus `trend_units_per_month` multiplied by the horizon
    offset, and that whole sum is multiplied by `seasonal_index`."

    Design: Difficulty/boundary_precision_check/demand_cv_exactly_at_intermittent_threshold_selects_croston
    """
    ctx = _cv_threshold_fixture()

    line = _cv_forecast(
        ctx["cycle"]["id"], ctx["below_threshold"]["id"], ctx["customer"]["id"]
    )
    assert line["method"] == "HOLT_WINTERS"
    assert line["baseline_units"] == 1452
    assert line["status"] == "BASELINE"
    assert line["consensus_units"] == line["baseline_units"]


def test_zero_request_row_carries_a_full_fill_rate():
    """A customer who asked for nothing still gets a row, and its fill rate is
    pinned at the full percentage rather than an undefined ratio.

    PRD: "except that a row whose `requested_units` is 0 carries a
    `fill_rate_pct` of exactly 100.00 rather than an undefined ratio."

    Design: Difficulty/boundary_precision_check/zero_request_customer_gets_full_fill_rate_on_ration
    """
    ctx = setup_five_customer_rationing(
        cycle_code="SOP-FILL-09", sku="SKU-BREAD-2"
    )
    plan = read_plan(ctx["plan"]["id"])
    assert plan["gross_requirement_units"] == 1400
    assert plan["demand_side_units"] == 1730
    assert plan["constrained_units"] == 900
    assert plan["status"] == "RATIONED"
    assert plan["unallocated_units"] == 0

    rows = list_plan_allocations(ctx["plan"]["id"])
    assert len(rows) == 5
    by_customer = {row["customer_id"]: row for row in rows}
    for row in rows:
        assert_allocation(row)

    dormant = by_customer[ctx["c5"]["id"]]
    assert dormant["requested_units"] == 0
    assert dormant["allocated_units"] == 0
    assert dormant["allocation_status"] == "ALLOCATED"
    assert dormant["allocation_pass"] == "NONE"
    assert float(dormant["fill_rate_pct"]) == 100.00

    held = by_customer[ctx["c4"]["id"]]
    assert held["requested_units"] == 200
    assert held["allocated_units"] == 0
    assert held["allocation_status"] == "WITHHELD_CREDIT_HOLD"
    assert held["allocation_pass"] == "NONE"
    assert float(held["fill_rate_pct"]) == 0.00


def test_largest_remainder_tie_break_favours_the_better_priority_rank():
    """Two pool members share an identical fractional share, so the extra unit is
    settled by rank rather than by row identity.

    PRD: "the pool is ordered by the fractional part of the exact share
    descending, then by `priority_rank` ascending, then by `created_at`
    ascending"

    Design: Difficulty/boundary_precision_check/zero_request_customer_gets_full_fill_rate_on_ration
    """
    ctx = setup_five_customer_rationing(
        cycle_code="SOP-FILL-09", sku="SKU-BREAD-2"
    )
    plan = read_plan(ctx["plan"]["id"])
    rows = list_plan_allocations(ctx["plan"]["id"])
    by_customer = {row["customer_id"]: row for row in rows}

    protected = by_customer[ctx["c1"]["id"]]
    assert protected["allocated_units"] == 400
    assert protected["allocation_pass"] == "PROTECTED"
    assert protected["allocation_status"] == "ALLOCATED"
    assert float(protected["fill_rate_pct"]) == 100.00

    winner = by_customer[ctx["c2"]["id"]]
    assert winner["allocated_units"] == 313
    assert winner["allocation_pass"] == "PRO_RATA"
    assert float(winner["fill_rate_pct"]) == 62.60

    loser = by_customer[ctx["c3"]["id"]]
    assert loser["allocated_units"] == 187
    assert loser["allocation_pass"] == "PRO_RATA"
    assert float(loser["fill_rate_pct"]) == 62.33

    assert sum(row["allocated_units"] for row in rows) == 900
    assert_allocation_units_conserved(plan, rows)


def _cereal_promotion_fixture():
    """One item, two customers, and four DRAFT promotions whose month windows abut,
    overlap or belong to a different customer."""
    family = create_family(family_code="FAM-CEREAL", name="Cereal")
    item = create_item(
        family["id"], sku="SKU-FLAKE-1", unit_price_cents=800, unit_cost_cents=300
    )
    customer_a = create_customer(
        customer_code="CUST-A", name="Alpha Grocery", channel="GROCERY", priority_rank=3
    )
    customer_b = create_customer(
        customer_code="CUST-B", name="Beta Club", channel="CLUB", priority_rank=4
    )
    p1 = create_promotion(
        item["id"],
        customer_a["id"],
        start_month="2026-10",
        end_month="2026-11",
        lift_pct=10,
        cannibalization_pct=2,
    )
    p2 = create_promotion(
        item["id"],
        customer_a["id"],
        start_month="2026-12",
        end_month="2027-01",
        lift_pct=12,
        cannibalization_pct=2,
    )
    p3 = create_promotion(
        item["id"],
        customer_a["id"],
        start_month="2026-11",
        end_month="2026-12",
        lift_pct=8,
        cannibalization_pct=1,
    )
    p4 = create_promotion(
        item["id"],
        customer_b["id"],
        start_month="2026-11",
        end_month="2026-12",
        lift_pct=8,
        cannibalization_pct=1,
    )
    return {"item": item, "p1": p1, "p2": p2, "p3": p3, "p4": p4}


def test_abutting_promotion_windows_are_not_an_overlap():
    """A window ending in November and one starting in December touch without
    sharing a month, so both approvals succeed while a window that shares
    November and December with them is refused.

    PRD: "Two closed windows overlap when they share at least one month; windows
    that merely abut, such as one ending `2026-09` and another starting
    `2026-10`, do not overlap."

    Design: Difficulty/resource_temporal_overlap/promotion_month_windows_closed_inclusive_adjacency_allowed
    """
    ctx = _cereal_promotion_fixture()

    first = approve_promotion(ctx["p1"]["id"])
    assert first["status"] == "APPROVED"

    second = validate_success(
        api_client.approve_promotion(ctx["p2"]["id"], LEAD, {}), 200
    )
    assert second["status"] == "APPROVED"

    validate_error(
        api_client.approve_promotion(ctx["p3"]["id"], LEAD, {}),
        ApiErrorId.ERR_PROMOTION_WINDOW_OVERLAP.value,
        409,
    )
    assert read_promotion(ctx["p3"]["id"])["status"] == "DRAFT"


def test_promotion_overlap_is_scoped_to_the_item_and_customer_pair():
    """The same months are free again for a different customer, because the
    constraint only looks at approved promotions of the same pair.

    PRD: "The promotion's month window must not overlap the window of any other
    `APPROVED` promotion for the same item and customer pair"

    Design: Difficulty/resource_temporal_overlap/promotion_month_windows_closed_inclusive_adjacency_allowed
    """
    ctx = _cereal_promotion_fixture()

    approve_promotion(ctx["p1"]["id"])
    approve_promotion(ctx["p2"]["id"])
    api_client.approve_promotion(ctx["p3"]["id"], LEAD, {})

    other_customer = validate_success(
        api_client.approve_promotion(ctx["p4"]["id"], LEAD, {}), 200
    )
    assert other_customer["status"] == "APPROVED"


def test_changeover_buffer_requires_two_clear_days_between_blocks():
    """Adjacency is not enough: the first legal start is the existing block's end
    date plus two days.

    PRD: "Anything closer than that — including two blocks that are exactly
    adjacent, where one block's `end_date` is the next block's `start_date` — is
    rejected with `ERR_CAPACITY_BLOCK_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/capacity_block_half_open_dates_with_changeover_buffer
    """
    family = create_family(
        family_code="FAM-LINE1", name="Line One", units_per_hour=100, max_monthly_hours=800
    )

    first = create_capacity_block(
        family["id"], start_date="2026-09-01", end_date="2026-09-10", available_hours=100
    )
    assert first["available_hours"] == 100

    validate_error(
        api_client.create_capacity_block(
            capacity_block_payload(
                family["id"],
                start_date="2026-09-10",
                end_date="2026-09-20",
                available_hours=100,
            ),
            SUPPLY,
        ),
        ApiErrorId.ERR_CAPACITY_BLOCK_OVERLAP.value,
        409,
    )
    validate_error(
        api_client.create_capacity_block(
            capacity_block_payload(
                family["id"],
                start_date="2026-09-11",
                end_date="2026-09-20",
                available_hours=100,
            ),
            SUPPLY,
        ),
        ApiErrorId.ERR_CAPACITY_BLOCK_OVERLAP.value,
        409,
    )

    cleared = create_capacity_block(
        family["id"], start_date="2026-09-12", end_date="2026-09-20", available_hours=100
    )
    assert cleared["start_date"] == "2026-09-12"


def test_monthly_hour_ceiling_buckets_blocks_by_start_date():
    """The two accepted blocks already hold two hundred hours in September, so a
    seven-hundred-hour block bucketed into the same month breaks the family
    ceiling and is refused.

    PRD: "Blocks are bucketed into calendar months by their `start_date` alone"

    Design: Difficulty/resource_temporal_overlap/capacity_block_half_open_dates_with_changeover_buffer
    """
    family = create_family(
        family_code="FAM-LINE1", name="Line One", units_per_hour=100, max_monthly_hours=800
    )
    create_capacity_block(
        family["id"], start_date="2026-09-01", end_date="2026-09-10", available_hours=100
    )
    api_client.create_capacity_block(
        capacity_block_payload(
            family["id"],
            start_date="2026-09-10",
            end_date="2026-09-20",
            available_hours=100,
        ),
        SUPPLY,
    )
    create_capacity_block(
        family["id"], start_date="2026-09-12", end_date="2026-09-20", available_hours=100
    )

    validate_error(
        api_client.create_capacity_block(
            capacity_block_payload(
                family["id"],
                start_date="2026-09-25",
                end_date="2026-09-30",
                available_hours=700,
            ),
            SUPPLY,
        ),
        ApiErrorId.ERR_FAMILY_MONTHLY_HOURS_EXCEEDED.value,
        422,
    )

    listing = api_client.list_capacity_blocks(
        SUPPLY, params={"family_id": family["id"], "limit": 100}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 2
    assert sum(float(row["available_hours"]) for row in rows) == 200
