"""Turnaround failover cascade and clock-driven completion."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_in_progress_turnaround,
    create_scheduled_turnaround,
    create_tank,
    list_tank_deliveries,
    post_telemetry,
    set_logical_clock,
    setup_standard_onsite_scenario,
    start_turnaround,
    validate_success,
)


def _get_turnaround(plant_id, turnaround_id):
    turnarounds = validate_success(api_client.list_plant_turnarounds(
        plant_id, TEST_USERS["plant_operator_headers"]
    ))
    match = [t for t in turnarounds if t["id"] == turnaround_id]
    assert len(match) == 1, f"turnaround {turnaround_id} not found on plant"
    return match[0]


def test_turnaround_start_failover_cascade(api):
    """PRD section 3.7: "A successful start moves the turnaround to
    `IN_PROGRESS` and fires the failover cascade: the plant moves from
    `OPERATING` to `TURNAROUND` with `effective_capacity_nm3h` zeroed, the
    contract's `failover_active` becomes true, and for every tank of the
    customer whose `product` matches the contract's product the system
    auto-creates a backup delivery — `triggered_by` `BACKUP`, quantity equal to
    the tank's current headroom — unless that tank already has an open
    delivery; stop sequences are then recomputed for the affected route date."

    Design: Difficulty/transitive_cascade/turnaround_start_failover_cascade
    """
    bundle = setup_standard_onsite_scenario()
    customer, contract, plant = (
        bundle["customer"], bundle["contract"], bundle["plant"],
    )
    tank = create_tank(customer["id"], reorder_point_liters=8000,
                       safety_stock_liters=2000)
    post_telemetry(tank["id"], "2026-10-05T00:00:00Z", 12000)
    assert list_tank_deliveries(tank["id"]) == [], (
        "level 12000 is above reorder 8000: NORMAL, no telemetry delivery"
    )
    turnaround = create_scheduled_turnaround(
        plant["id"], customer["id"],
        window_start="2026-10-10T00:00:00Z", window_end="2026-10-14T00:00:00Z",
        scope="Cold box re-liquefier overhaul",
    )
    set_logical_clock("2026-10-10T00:00:00Z")

    started = start_turnaround(turnaround["id"])
    assert started["status"] == "IN_PROGRESS"

    plant_after = validate_success(api_client.get_plant(
        plant["id"], TEST_USERS["plant_operator_headers"]
    ))
    assert plant_after["status"] == "TURNAROUND"
    assert plant_after["effective_capacity_nm3h"] == 0

    contract_after = validate_success(api_client.get_contract(
        contract["id"], TEST_USERS["plant_operator_headers"]
    ))
    assert contract_after["failover_active"] is True

    deliveries = list_tank_deliveries(tank["id"])
    assert len(deliveries) == 1, (
        f"exactly one backup delivery must be dispatched, got {len(deliveries)}"
    )
    backup = deliveries[0]
    assert backup["triggered_by"] == "BACKUP"
    assert backup["quantity_liters"] == 38000, (
        f"headroom 50000 - 12000 sizes the backup at 38000, got {backup['quantity_liters']}"
    )
    assert backup["stop_sequence"] == 1


def test_turnaround_auto_completes_at_window_end(api):
    """PRD section 2.4: "Any turnaround in `IN_PROGRESS` whose `window_end` is
    at or before the current time completes, returning its plant to `OPERATING`
    and clearing the contract's failover flag (see §3.7)."
    PRD section 3.7: "When the logical clock reaches `window_end`, the
    turnaround moves to `COMPLETED`, the plant returns from `TURNAROUND` to
    `OPERATING` with effective capacity restored to the nameplate, and
    `failover_active` clears to false."

    Design: Corner/state_machines/turnaround_auto_completes_at_window_end
    """
    bundle = setup_standard_onsite_scenario()
    customer, contract, plant = (
        bundle["customer"], bundle["contract"], bundle["plant"],
    )
    turnaround = create_in_progress_turnaround(
        plant["id"], customer["id"],
        window_start="2026-10-10T00:00:00Z", window_end="2026-10-14T00:00:00Z",
        scope="Completion check",
    )
    set_logical_clock("2026-10-14T00:00:00Z")

    after = _get_turnaround(plant["id"], turnaround["id"])
    assert after["status"] == "COMPLETED", (
        f"the sweep at exactly window_end completes the turnaround, got {after['status']}"
    )
    plant_after = validate_success(api_client.get_plant(
        plant["id"], TEST_USERS["plant_operator_headers"]
    ))
    assert plant_after["status"] == "OPERATING"
    assert plant_after["effective_capacity_nm3h"] == 6000, (
        "nameplate capacity is restored on completion"
    )
    contract_after = validate_success(api_client.get_contract(
        contract["id"], TEST_USERS["plant_operator_headers"]
    ))
    assert contract_after["failover_active"] is False
