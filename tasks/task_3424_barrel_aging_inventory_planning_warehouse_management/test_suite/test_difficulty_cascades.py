"""Difficulty-design translations: transitive cascades along the
project -> rickhouse -> slot tree and back up through posture (PRD §2.9).
"""
from datetime import datetime

from test_helpers import (
    DEFAULT_CLOCK_ISO,
    LIMIT_MAX,
    assert_rickhouse,
    assert_warehouse_slot,
    commission_date_for,
    create_commissioned_rickhouse,
    create_expansion_project_payload,
    fill_barrels_on_slots,
    get_success_data,
    set_clock,
    validate_success,
)


def _instant(iso: str) -> datetime:
    """Parse an ISO 8601 UTC instant (fractional seconds optional)."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_commission_cascade_materializes_slots_and_posture(
    api, distillery_planner_headers, operations_director_headers, platform_admin_headers
):
    """PRD §3.1: "Commissioning stamps `commissioned_at`, increments the
    project's `version`, moves the project to its terminal `COMMISSIONED`
    state, and fires a multi-part cascade: the rickhouse transitions `PLANNED`
    → `OPERATING`; the full slot grid materializes — exactly the product of
    `floors`, `rows_per_floor`, and `positions_per_row` slots, one per
    combination, enumerated in `floor_index`, then `row_index`, then
    `position_index` ascending order, each index 1-based with `floor_index` 1
    at ground level; every slot records its `rickhouse_id` and a computed
    `heat_factor`; and the rickhouse's `occupied_slots` initializes to zero
    with its posture recomputed — still `OPERATING` at zero occupancy."
    PRD §3.1: "A rickhouse's slot listing always returns this deterministic
    floor-row-position order."

    Design: Difficulty/transitive_cascade/commission_cascade_materializes_slots_and_posture
    """
    set_clock(DEFAULT_CLOCK_ISO)
    payload = create_expansion_project_payload(
        name="RH-CC",
        floors=2,
        rows_per_floor=2,
        positions_per_row=2,
        planned_annual_distillation_liters=80000,
    )
    project = validate_success(
        api.create_expansion_project(payload, distillery_planner_headers), expected_status=201
    )
    approved = validate_success(api.approve_expansion_project(project["id"], operations_director_headers))
    assert approved["state"] == "APPROVED"

    commission_iso = commission_date_for(approved["approved_at"], approved["construction_lag_months"])
    set_clock(commission_iso)
    commissioned = validate_success(
        api.commission_expansion_project(project["id"], operations_director_headers)
    )
    assert commissioned["state"] == "COMMISSIONED"
    assert _instant(commissioned["commissioned_at"]) == _instant(commission_iso)

    rickhouses = get_success_data(
        api.list_rickhouses(platform_admin_headers, params={"expansion_project_id": project["id"]})
    )
    assert len(rickhouses) == 1, "approval cascade created exactly one rickhouse"
    rickhouse = rickhouses[0]
    assert_rickhouse(rickhouse)
    assert rickhouse["posture"] == "OPERATING"
    assert rickhouse["total_slots"] == 8
    assert rickhouse["occupied_slots"] == 0

    slots = get_success_data(
        api.list_rickhouse_slots(rickhouse["id"], platform_admin_headers, params={"limit": LIMIT_MAX})
    )
    assert len(slots) == 8, "2 floors x 2 rows x 2 positions materialized"
    for slot in slots:
        assert_warehouse_slot(slot)
        assert slot["rickhouse_id"] == rickhouse["id"]
    # Fifth entry in (floor_index, row_index, position_index) ascending order is
    # (2, 1, 1): the first slot of the second floor, heat_factor 1.05.
    fifth = slots[4]
    assert (fifth["floor_index"], fifth["row_index"], fifth["position_index"]) == (2, 1, 1)
    assert fifth["heat_factor"] == 1.05


def test_dump_cascade_frees_slot_and_flips_posture(api, warehouse_manager_headers):
    """PRD §3.4: "A dump cascades: the barrel's `OPEN` occupancy, if any,
    closes — `end_at` stamped with the current clock, `status` becoming
    `CLOSED`, and `current_slot_id` becoming null; the affected rickhouse's
    `occupied_slots` decreases by one; and the house's posture recomputes,
    flipping `FULL` → `OPERATING` when occupancy falls below capacity."

    Design: Difficulty/transitive_cascade/dump_cascade_frees_slot_and_flips_posture
    """
    ctx = create_commissioned_rickhouse(
        floors=1, rows_per_floor=2, positions_per_row=2, name="RH-DC",
    )
    barrels = fill_barrels_on_slots(
        [s["id"] for s in ctx["slots"]],
        fill_volume_liters=100.0,
        min_maturation_months=12,
    )
    rickhouse_id = ctx["rickhouse"]["id"]
    full = validate_success(api.get_rickhouse(rickhouse_id, warehouse_manager_headers))
    assert full["occupied_slots"] == 4
    assert full["posture"] == "FULL"

    set_clock("2028-10-01T00:00:00Z")
    dumped = validate_success(api.dump_barrel(barrels[0]["id"], warehouse_manager_headers))
    assert dumped["maturation_status"] == "DUMPED"
    assert dumped["current_slot_id"] is None

    occupancies = get_success_data(
        api.list_barrel_occupancies(barrels[0]["id"], warehouse_manager_headers)
    )
    assert len(occupancies) == 1
    assert occupancies[0]["status"] == "CLOSED"
    assert _instant(occupancies[0]["end_at"]) == _instant("2028-10-01T00:00:00Z")

    after = validate_success(api.get_rickhouse(rickhouse_id, warehouse_manager_headers))
    assert after["occupied_slots"] == 3
    assert after["posture"] == "OPERATING"
