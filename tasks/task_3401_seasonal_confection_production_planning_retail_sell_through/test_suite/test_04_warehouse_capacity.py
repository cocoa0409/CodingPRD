"""Warehouse load arithmetic: the inclusive 85% congestion floor, the
overflow gate, and the directional CONGESTED seasonal block.
"""
from test_helpers import (
    ApiErrorId,
    ProductionRunStatus,
    WarehousePosture,
    TEST_USERS,
    api_client,
    complete_run,
    complete_run_payload,
    create_scheduled_run,
    get_production_run,
    get_warehouse,
    setup_warehouse_with_load,
    start_run,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["production_planner_headers"]


# ---------------------------------------------------------------------------
# Boundary precision: the inclusive congestion floor at floor(0.85 x capacity)
# ---------------------------------------------------------------------------

def test_posture_open_just_below_congestion_floor(api):
    """PRD §2.9: "otherwise, if `in_use_units` is at least the floor of 85% of
    `capacity_units` (the congestion threshold is the constant 0.85, applied
    with a floor before comparison), posture is `CONGESTED`; otherwise posture
    is `OPEN`. Sitting exactly at the 85% floor is `CONGESTED`, not `OPEN`."

    Design: Difficulty/boundary_precision_check/warehouse_congested_at_exactly_eighty_five_percent_load
    """
    world = setup_warehouse_with_load(849, capacity=1000)
    warehouse = get_warehouse(world["warehouse"]["id"])
    assert warehouse["in_use_units"] == 849
    # 849 < floor(0.85 x 1000) == 850, so the warehouse is still OPEN.
    assert warehouse["posture"] == WarehousePosture.OPEN.value


def test_posture_congested_at_exact_congestion_floor(api):
    """PRD §2.9: "Sitting exactly at the 85% floor is `CONGESTED`, not `OPEN`;
    sitting exactly at capacity is `FULL`, not `CONGESTED`."

    Design: Difficulty/boundary_precision_check/warehouse_congested_at_exactly_eighty_five_percent_load
    """
    world = setup_warehouse_with_load(849, capacity=1000)
    run2 = create_scheduled_run(
        world["product"], world["program"], planned_units=1, line_code="LINE-B",
    )
    start_run(run2)
    # Pre-add posture is OPEN (849 < 850), so the seasonal CONGESTED block
    # does not fire; 849 + 1 = 850 <= 1000, so the overflow gate passes too.
    completed = complete_run(run2, world["warehouse"], 1)
    assert completed["status"] == ProductionRunStatus.COMPLETE.value

    warehouse = get_warehouse(world["warehouse"]["id"])
    assert warehouse["in_use_units"] == 850
    assert warehouse["posture"] == WarehousePosture.CONGESTED.value  # inclusive >=


# ---------------------------------------------------------------------------
# Aggregate overflow gate: arithmetic, not the posture label
# ---------------------------------------------------------------------------

def _setup_overfull_scenario():
    """W1 capacity 1000 holding 950 (CONGESTED); one IN_PROGRESS EVERYDAY run
    of 100 units targeting W1."""
    world = setup_warehouse_with_load(950, capacity=1000, with_everyday_product=True)
    run2 = create_scheduled_run(
        world["everyday_product"], None, planned_units=100, line_code="LINE-B",
        scheduled_start_on="2027-03-10T08:00:00Z",
        scheduled_end_on="2027-03-11T08:00:00Z",
    )
    start_run(run2)
    return world, run2


def test_complete_overflowing_warehouse_rejected(api):
    """PRD §2.9: "Completing a production run into a warehouse is rejected
    with `ERR_WAREHOUSE_FULL` (HTTP 409) when the warehouse's `in_use_units`
    plus the run's produced units would exceed `capacity_units`, or when the
    warehouse is already in `FULL` posture."

    Design: Difficulty/resource_temporal_overlap/warehouse_capacity_rejects_completion_that_would_overflow
    """
    world, run2 = _setup_overfull_scenario()
    resp = api_client.complete_production_run(
        run2["id"],
        complete_run_payload(warehouse_id=world["warehouse"]["id"], produced_units=100),
        PLANNER,
    )
    # 950 + 100 = 1050 > 1000 — the arithmetic guard decides.
    validate_error(resp, ApiErrorId.ERR_WAREHOUSE_FULL)


def test_overflow_rejection_leaves_no_residue(api):
    """PRD §2.9: "Completing a production run into a warehouse is rejected
    with `ERR_WAREHOUSE_FULL` (HTTP 409) when the warehouse's `in_use_units`
    plus the run's produced units would exceed `capacity_units`"."

    Design: Difficulty/resource_temporal_overlap/warehouse_capacity_rejects_completion_that_would_overflow
    """
    world, run2 = _setup_overfull_scenario()
    resp = api_client.complete_production_run(
        run2["id"],
        complete_run_payload(warehouse_id=world["warehouse"]["id"], produced_units=100),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_WAREHOUSE_FULL)

    warehouse = get_warehouse(world["warehouse"]["id"])
    assert warehouse["in_use_units"] == 950, "no partial lot may be created"
    assert warehouse["posture"] == WarehousePosture.CONGESTED.value
    # The failed complete leaves the run IN_PROGRESS.
    assert get_production_run(run2["id"])["status"] == ProductionRunStatus.IN_PROGRESS.value


# ---------------------------------------------------------------------------
# CONGESTED is directional: seasonal inbound blocked, everyday flows
# ---------------------------------------------------------------------------

def test_congested_warehouse_blocks_seasonal_completion_but_not_everyday(api):
    """PRD §2.9: "A warehouse in `CONGESTED` posture refuses additional
    **seasonal** inbound lots — completing a seasonal run into it is rejected
    with `ERR_WAREHOUSE_CONGESTED_SEASONAL` (HTTP 409) — while everyday lots
    are still accepted, because the everyday business must keep flowing even
    when a warehouse is nearly full."

    Design: Corner/errors/congested_warehouse_blocks_seasonal_completion_but_not_everyday
    """
    world = setup_warehouse_with_load(850, capacity=1000, with_everyday_product=True)
    run_seas = create_scheduled_run(
        world["product"], world["program"], planned_units=50, line_code="LINE-B",
        scheduled_start_on="2027-03-10T08:00:00Z",
        scheduled_end_on="2027-03-11T08:00:00Z",
    )
    run_ev = create_scheduled_run(
        world["everyday_product"], None, planned_units=50, line_code="LINE-B",
        scheduled_start_on="2027-03-20T08:00:00Z",
        scheduled_end_on="2027-03-21T08:00:00Z",
    )
    start_run(run_seas)
    start_run(run_ev)

    # 850 + 50 = 900 <= 1000: the posture gate, not capacity, fires.
    resp = api_client.complete_production_run(
        run_seas["id"],
        complete_run_payload(warehouse_id=world["warehouse"]["id"], produced_units=50),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_WAREHOUSE_CONGESTED_SEASONAL)
    assert get_production_run(run_seas["id"])["status"] == ProductionRunStatus.IN_PROGRESS.value

    completed = complete_run(run_ev, world["warehouse"], 50)
    assert completed["status"] == ProductionRunStatus.COMPLETE.value
    warehouse = get_warehouse(world["warehouse"]["id"])
    assert warehouse["in_use_units"] == 900
    assert warehouse["posture"] == WarehousePosture.CONGESTED.value
