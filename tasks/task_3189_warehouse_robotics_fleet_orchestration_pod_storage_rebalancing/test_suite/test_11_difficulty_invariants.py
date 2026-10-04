"""Queue A (difficulty) translations: compensating invariants.

Covers rule_id compensating_invariant:
- sku_reserved_units_invariant_across_cancel (2 tests)
- fleet_status_count_conservation_across_charge_cycle (2 tests)
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_paginated,
    set_clock,
    create_zone,
    create_charger,
    create_drive_unit,
    create_sku,
    create_pick_station,
    create_pod,
    create_order_with_line,
    create_pick_task_payload,
    create_charging_session_payload,
    get_station_version,
    get_sku,
    stow_units,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
FLOW = TEST_USERS["flow_controller_headers"]


def _setup_reserved_invariant_scenario():
    """Stocked pod with 5 units of SKU1; order with line qty 2; SKU
    total_units_reserved observed before sequencing."""
    set_clock("2026-09-01T08:00:00Z")
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                       max_human_occupancy=2)
    pod = create_pod(zone["id"], pod_code="P1", slot_capacity=5)
    sku = create_sku(sku_code="SKU1", velocity_class="LOW")
    station = create_pick_station(zone["id"], station_code="ST1", max_queue=5)
    stow_units(sku, quantity=5)
    reserved_before = get_sku(sku["id"])["total_units_reserved"]
    order, line = create_order_with_line(sku["id"], quantity=2)
    task = get_success_data(
        api_client.create_pick_task(
            create_pick_task_payload(
                order["id"], line["id"], pod["id"], station["id"], quantity=2
            ),
            FLOW,
        )
    )
    return {
        "zone": zone, "pod": pod, "sku": sku, "station": station,
        "order": order, "task": task, "reserved_before": reserved_before,
    }


def test_sequence_then_cancel_restores_sku_reserved_units(api):
    """PRD §3.3: "the slot's `quantity_reserved` and the SKU's
    `total_units_reserved` each increase by the task's `quantity`."
    PRD §3.3: "from `QUEUED` the cancellation releases everything sequencing
    claimed: station `queue_length` decreases by 1, the pod returns `RESERVED`
    → `IN_STORAGE`, and the slot's `quantity_reserved` and the SKU's
    `total_units_reserved` each decrease by the task's quantity."

    Design: Difficulty/compensating_invariant/sku_reserved_units_invariant_across_cancel
    """
    env = _setup_reserved_invariant_scenario()
    assert env["reserved_before"] == 0
    get_success_data(
        api_client.sequence_pick_task(
            env["task"]["id"], get_station_version(env["station"]["id"]), FLOW
        )
    )
    assert get_sku(env["sku"]["id"])["total_units_reserved"] == 2
    get_success_data(api_client.cancel_pick_task(env["task"]["id"], FLOW))
    reserved_after = get_sku(env["sku"]["id"])["total_units_reserved"]
    assert reserved_after == env["reserved_before"], (
        f"compensating invariant violated: reserved {reserved_after} != "
        f"{env['reserved_before']} after sequence+cancel"
    )


def test_sequence_increments_sku_reserved_by_task_quantity(api):
    """PRD §3.3: "the slot's `quantity_reserved` and the SKU's
    `total_units_reserved` each increase by the task's `quantity`."

    Design: Difficulty/compensating_invariant/sku_reserved_units_invariant_across_cancel
    """
    env = _setup_reserved_invariant_scenario()
    get_success_data(
        api_client.sequence_pick_task(
            env["task"]["id"], get_station_version(env["station"]["id"]), FLOW
        )
    )
    assert get_sku(env["sku"]["id"])["total_units_reserved"] == 2, (
        "sequencing a qty-2 task must raise total_units_reserved by exactly 2"
    )


def _setup_two_units_and_charger():
    set_clock("2026-09-01T08:00:00Z")
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                       max_human_occupancy=2)
    charger = create_charger(zone["id"], slot_count=1)
    du1 = create_drive_unit(zone["id"], unit_code="DU1")
    du2 = create_drive_unit(zone["id"], unit_code="DU2")
    return zone, charger, du1, du2


def _fleet_total():
    _data, meta = validate_paginated(api_client.list_drive_units(ADMIN))
    return meta["total_count"]


def test_fleet_count_conserved_across_charge_cycle(api):
    """PRD §3.5: "Opening transitions the unit `ACTIVE` → `CHARGING`."
    PRD §3.5: "Closing transitions the session `OPEN` → `CLOSED` ... returns
    the unit `CHARGING` → `ACTIVE`."

    Design: Difficulty/compensating_invariant/fleet_status_count_conservation_across_charge_cycle
    """
    _zone, charger, du1, _du2 = _setup_two_units_and_charger()
    total_before = _fleet_total()
    assert total_before == 2
    session = get_success_data(
        api_client.create_charging_session(
            create_charging_session_payload(charger["id"], du1["id"]), FLOW
        )
    )
    set_clock("2026-09-01T09:00:00Z")
    get_success_data(api_client.close_charging_session(session["id"], FLOW))
    total_after = _fleet_total()
    assert total_after == total_before, (
        f"fleet size must be conserved across a charge cycle: "
        f"{total_before} -> {total_after}"
    )


def test_unit_returns_active_after_charge_cycle(api):
    """PRD §3.5: "Closing transitions the session `OPEN` → `CLOSED`, restores
    the unit's `battery_pct` to the smaller of 100 and the current level plus
    the credit, increments `charge_cycle_count` by 1, decrements the charger's
    `slots_in_use` by 1, returns the unit `CHARGING` → `ACTIVE`, and
    increments the unit's `version`."

    Design: Difficulty/compensating_invariant/fleet_status_count_conservation_across_charge_cycle
    """
    _zone, charger, du1, _du2 = _setup_two_units_and_charger()
    session = get_success_data(
        api_client.create_charging_session(
            create_charging_session_payload(charger["id"], du1["id"]), FLOW
        )
    )
    set_clock("2026-09-01T09:00:00Z")
    get_success_data(api_client.close_charging_session(session["id"], FLOW))
    unit_after = get_success_data(api_client.get_drive_unit(du1["id"], ADMIN))
    assert unit_after["status"] == "ACTIVE", (
        f"unit must return to ACTIVE after the charge cycle, got {unit_after['status']}"
    )
