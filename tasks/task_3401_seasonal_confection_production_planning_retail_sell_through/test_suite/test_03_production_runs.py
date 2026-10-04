"""Production runs: run completion cascades, the program-state start gate,
line changeover/overlap discipline, cancel conservation, and the seasonal
production deadline.
"""
from datetime import datetime

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_AT_COMMITMENT_CLOSE,
    InventoryLotStatus,
    ProductionRunStatus,
    ProgramAdvanceTarget,
    SeasonalProgramStatus,
    WarehousePosture,
    TEST_USERS,
    advance_program_to,
    api_client,
    assert_production_run,
    complete_run,
    create_production_run_payload,
    create_scheduled_run,
    get_lot_for_run,
    get_production_run,
    get_program,
    get_warehouse,
    set_clock,
    setup_locked_with_in_progress_run,
    setup_open_program,
    start_run,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def _hours(run) -> float:
    start = datetime.fromisoformat(run["scheduled_start_on"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(run["scheduled_end_on"].replace("Z", "+00:00"))
    return (end - start).total_seconds() / 3600.0


def _active_runs_on_line(line_code: str):
    rows, _meta = validate_paginated(
        api_client.list_production_runs(ADMIN, params={"line_code": line_code})
    )
    return [r for r in rows if r["status"] != ProductionRunStatus.CANCELLED.value]


# ---------------------------------------------------------------------------
# Run completion cascade: lot creation + warehouse load + posture flip
# ---------------------------------------------------------------------------

def test_run_complete_creates_single_available_lot(api):
    """PRD §3.2: "Completion cascades: it creates exactly one `InventoryLot`
    for the run, stamped with the run's `product_id`, the receiving
    `warehouse_id`, and the run's id as `production_run_id`, with
    `units_on_hand` equal to `produced_units` and status `AVAILABLE`".

    Design: Difficulty/transitive_cascade/run_complete_creates_lot_recomputes_warehouse_load_flips_posture
    """
    world = setup_locked_with_in_progress_run(planned_units=850, warehouse_capacity=1000)
    completed = complete_run(world["run"], world["warehouse"], 850)
    assert completed["status"] == ProductionRunStatus.COMPLETE.value
    assert completed["produced_units"] == 850
    assert completed["completed_warehouse_id"] == world["warehouse"]["id"]

    rows, _meta = validate_paginated(api_client.list_inventory_lots(
        ADMIN, params={"production_run_id": world["run"]["id"]},
    ))
    assert len(rows) == 1, "exactly one lot per completing run"
    lot = rows[0]
    assert lot["units_on_hand"] == 850
    assert lot["status"] == InventoryLotStatus.AVAILABLE.value
    assert lot["product_id"] == world["product"]["id"]
    assert lot["warehouse_id"] == world["warehouse"]["id"]


def test_run_complete_recomputes_load_and_flips_posture(api):
    """PRD §2.9: "if `in_use_units` is at least the floor of 85% of
    `capacity_units` (the congestion threshold is the constant 0.85, applied
    with a floor before comparison), posture is `CONGESTED`". PRD §3.2:
    "Completion then recomputes the warehouse's `in_use_units` and posture per
    Section 2.9, and — for seasonal runs only — refreshes the program's
    `produced_units_total`".

    Design: Difficulty/transitive_cascade/run_complete_creates_lot_recomputes_warehouse_load_flips_posture
    """
    world = setup_locked_with_in_progress_run(planned_units=850, warehouse_capacity=1000)
    before = get_warehouse(world["warehouse"]["id"])
    assert before["in_use_units"] == 0
    assert before["posture"] == WarehousePosture.OPEN.value

    complete_run(world["run"], world["warehouse"], 850)

    after = get_warehouse(world["warehouse"]["id"])
    assert after["in_use_units"] == 850
    assert after["posture"] == WarehousePosture.CONGESTED.value  # 850 >= floor(0.85*1000)
    program = get_program(world["program"]["id"])
    assert program["produced_units_total"] == 850


# ---------------------------------------------------------------------------
# Cross-entity start gate: seasonal runs need program LOCKED/IN_PRODUCTION
# ---------------------------------------------------------------------------

def test_seasonal_run_start_rejected_while_program_open(api):
    """PRD §3.2: "For a seasonal product, the program must be in `LOCKED` or
    `IN_PRODUCTION` status — production cannot begin while commitments are
    still being collected — or the start is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/run_start_requires_program_locked_or_in_production
    """
    world = setup_open_program()
    run = create_scheduled_run(world["product"], world["program"], planned_units=10)

    resp = api_client.start_production_run(run["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_production_run(run["id"])["status"] == ProductionRunStatus.SCHEDULED.value


def test_seasonal_run_start_succeeds_once_program_locked(api):
    """PRD §3.2: "For a seasonal product, the program must be in `LOCKED` or
    `IN_PRODUCTION` status — production cannot begin while commitments are
    still being collected — or the start is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/run_start_requires_program_locked_or_in_production
    """
    world = setup_open_program()
    run = create_scheduled_run(world["product"], world["program"], planned_units=10)

    set_clock(CLOCK_AT_COMMITMENT_CLOSE)
    advance_program_to(world["program"]["id"], ProgramAdvanceTarget.LOCKED.value)

    started = start_run(run)
    assert started["status"] == ProductionRunStatus.IN_PROGRESS.value
    assert started["version"] == run["version"] + 1


# ---------------------------------------------------------------------------
# Line changeover buffer: inclusive 8h on kind switch
# ---------------------------------------------------------------------------

def _setup_line1_with_kind_switch():
    """LINE-1: run A EVERYDAY 03-01T08:00 -> 03-05T08:00; run B SEASONAL
    03-05T16:00 -> 03-06T08:00 (exactly the 8h buffer after A)."""
    world = setup_open_program(with_everyday_product=True)
    run_a = create_scheduled_run(
        world["everyday_product"], None, planned_units=500, line_code="LINE-1",
        scheduled_start_on="2027-03-01T08:00:00Z",
        scheduled_end_on="2027-03-05T08:00:00Z",
    )
    run_b = create_scheduled_run(
        world["product"], world["program"], planned_units=300, line_code="LINE-1",
        scheduled_start_on="2027-03-05T16:00:00Z",
        scheduled_end_on="2027-03-06T08:00:00Z",
    )
    return world, run_a, run_b


def test_changeover_exactly_eight_hour_gap_accepted(api):
    """PRD §2.10: "If a prior run exists and its product's kind differs from
    the new run's product's kind — a seasonal/everyday switch in either
    direction — the new run must start at least 8 hours after the prior run's
    `scheduled_end_on`; a changeover buffer shorter than that is rejected with
    `ERR_CHANGEOVER_VIOLATION` (HTTP 422). The 8-hour buffer is inclusive: a
    gap of exactly 8 hours passes."

    Design: Difficulty/resource_temporal_overlap/line_changeover_requires_exact_eight_hour_gap_on_kind_switch
    """
    _world, run_a, run_b = _setup_line1_with_kind_switch()
    # Both creates succeeded: B starts exactly 8h after A ends on a kind switch.
    assert run_a["status"] == ProductionRunStatus.SCHEDULED.value
    assert run_b["status"] == ProductionRunStatus.SCHEDULED.value
    rows = _active_runs_on_line("LINE-1")
    assert len(rows) == 2


def test_changeover_one_second_short_rejected(api):
    """PRD §2.10: "Two checks run, **overlap first, then changeover**." and
    "a changeover buffer shorter than that is rejected with
    `ERR_CHANGEOVER_VIOLATION` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/line_changeover_requires_exact_eight_hour_gap_on_kind_switch
    """
    world, _run_a, _run_b = _setup_line1_with_kind_switch()
    # Run C: 1 second after A's end on a kind switch; intersects neither A nor B.
    resp = api_client.create_production_run(
        create_production_run_payload(
            product_id=world["product"]["id"], program_id=world["program"]["id"],
            line_code="LINE-1", planned_units=200,
            scheduled_start_on="2027-03-05T08:00:01Z",
            scheduled_end_on="2027-03-05T14:00:00Z",
        ),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_CHANGEOVER_VIOLATION)
    rows = _active_runs_on_line("LINE-1")
    assert len(rows) == 2, "the rejected run must not be persisted"


# ---------------------------------------------------------------------------
# Cancel conservation: cancelled runs leave the schedule checks
# ---------------------------------------------------------------------------

def _setup_line9_baseline():
    """LINE-9: one EVERYDAY run 03-01T08:00 -> 03-05T08:00 (96h)."""
    world = setup_open_program(with_everyday_product=True)
    run1 = create_scheduled_run(
        world["everyday_product"], None, planned_units=500, line_code="LINE-9",
        scheduled_start_on="2027-03-01T08:00:00Z",
        scheduled_end_on="2027-03-05T08:00:00Z",
    )
    return world, run1


def test_cancelled_run_drops_out_of_overlap_checks(api):
    """PRD §2.10: "Production runs are scheduled against a free-form
    `line_code`, and every new run is checked against the other
    non-`CANCELLED` runs sharing that line; a cancelled run no longer
    participates in either check."

    Design: Difficulty/compensating_invariant/run_create_then_cancel_leaves_line_scheduled_hours_unchanged
    """
    world, run1 = _setup_line9_baseline()
    run2 = create_scheduled_run(
        world["everyday_product"], None, planned_units=100, line_code="LINE-9",
        scheduled_start_on="2027-03-10T08:00:00Z",
        scheduled_end_on="2027-03-11T08:00:00Z",
    )
    cancelled = api_client.cancel_production_run(run2["id"], PLANNER)
    validate_success(cancelled, 200)

    # R3 reuses R2's exact slot start; only possible because R2 is cancelled.
    run3 = create_scheduled_run(
        world["everyday_product"], None, planned_units=50, line_code="LINE-9",
        scheduled_start_on="2027-03-10T08:00:00Z",
        scheduled_end_on="2027-03-10T12:00:00Z",
    )
    assert run3["status"] == ProductionRunStatus.SCHEDULED.value
    assert get_production_run(run2["id"])["status"] == ProductionRunStatus.CANCELLED.value
    assert get_production_run(run1["id"])["status"] == ProductionRunStatus.SCHEDULED.value


def test_run_create_then_cancel_conserves_line_hours(api):
    """PRD §2.10: "a cancelled run no longer participates in either check."

    Design: Difficulty/compensating_invariant/run_create_then_cancel_leaves_line_scheduled_hours_unchanged
    """
    world, run1 = _setup_line9_baseline()
    baseline = sum(_hours(r) for r in _active_runs_on_line("LINE-9"))
    assert baseline == pytest.approx(96.0)

    run2 = create_scheduled_run(
        world["everyday_product"], None, planned_units=100, line_code="LINE-9",
        scheduled_start_on="2027-03-10T08:00:00Z",
        scheduled_end_on="2027-03-11T08:00:00Z",
    )
    grown = sum(_hours(r) for r in _active_runs_on_line("LINE-9"))
    assert grown == pytest.approx(120.0)  # 96 + 24

    validate_success(api_client.cancel_production_run(run2["id"], PLANNER), 200)
    restored = sum(_hours(r) for r in _active_runs_on_line("LINE-9"))
    assert restored == pytest.approx(96.0), (
        "the create+cancel pair conserves scheduled line-hours"
    )


# ---------------------------------------------------------------------------
# Seasonal production deadline
# ---------------------------------------------------------------------------

def test_seasonal_run_past_production_deadline_rejected_but_everyday_allowed(api):
    """PRD §3.2: "A seasonal run's `scheduled_end_on` must not fall after the
    program's `production_deadline_on`, or the create is rejected with
    `ERR_PRODUCTION_DEADLINE_VIOLATION` (HTTP 422)." The default program's
    deadline is 2027-06-30T00:00:00Z; the gate is a seasonal-program concept,
    so an everyday run (null program_id) has no deadline to violate.

    Design: Corner/validations/seasonal_run_past_production_deadline_rejected_but_everyday_allowed
    """
    world = setup_open_program(with_everyday_product=True)
    seasonal = api_client.create_production_run(
        create_production_run_payload(
            product_id=world["product"]["id"], program_id=world["program"]["id"],
            line_code="LINE-A", planned_units=10,
            scheduled_start_on="2027-06-30T08:00:00Z",
            scheduled_end_on="2027-07-01T08:00:00Z",
        ),
        PLANNER,
    )
    validate_error(seasonal, ApiErrorId.ERR_PRODUCTION_DEADLINE_VIOLATION)

    everyday = api_client.create_production_run(
        create_production_run_payload(
            product_id=world["everyday_product"]["id"], program_id=None,
            line_code="LINE-A", planned_units=10,
            scheduled_start_on="2027-06-30T08:00:00Z",
            scheduled_end_on="2027-07-01T08:00:00Z",
        ),
        PLANNER,
    )
    data = validate_success(everyday, 201)
    assert data["status"] == ProductionRunStatus.SCHEDULED.value
