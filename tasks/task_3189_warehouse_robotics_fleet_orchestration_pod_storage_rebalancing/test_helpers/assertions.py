"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1: {data}"
    )


def assert_floor_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["grid_x"], int) and data["grid_x"] >= 0
    assert isinstance(data["grid_y"], int) and data["grid_y"] >= 0
    assert isinstance(data["width"], int) and data["width"] >= 1
    assert isinstance(data["height"], int) and data["height"] >= 1
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["max_human_occupancy"], int)
    assert data["max_human_occupancy"] >= 1


def assert_drive_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_code"], str) and data["unit_code"]
    assert data["status"] in (
        "ACTIVE", "EN_ROUTE", "AT_STATION", "PARKED",
        "CHARGING", "MAINTENANCE", "STRANDED", "RETIRED",
    )
    assert isinstance(data["home_zone_id"], str)
    assert isinstance(data["battery_pct"], int)
    assert 0 <= data["battery_pct"] <= 100
    assert isinstance(data["odometer_cells"], int) and data["odometer_cells"] >= 0
    assert isinstance(data["charge_cycle_count"], int)
    assert data["charge_cycle_count"] >= 0


def assert_charger(data: dict):
    _assert_common(data)
    assert isinstance(data["zone_id"], str)
    assert isinstance(data["slot_count"], int) and data["slot_count"] >= 1
    assert isinstance(data["slots_in_use"], int) and data["slots_in_use"] >= 0


def assert_pod(data: dict):
    _assert_common(data)
    assert isinstance(data["pod_code"], str) and data["pod_code"]
    assert isinstance(data["zone_id"], str)
    assert isinstance(data["slot_capacity"], int) and data["slot_capacity"] >= 1
    assert isinstance(data["slots_used"], int) and data["slots_used"] >= 0
    assert data["status"] in ("IN_STORAGE", "RESERVED", "AT_STATION", "QUARANTINED")


def assert_sku(data: dict):
    _assert_common(data)
    assert isinstance(data["sku_code"], str) and data["sku_code"]
    assert data["velocity_class"] in ("HIGH", "MEDIUM", "LOW")
    assert isinstance(data["total_units_on_hand"], int)
    assert data["total_units_on_hand"] >= 0
    assert isinstance(data["total_units_reserved"], int)
    assert data["total_units_reserved"] >= 0


def assert_inventory_slot(data: dict):
    _assert_common(data)
    assert isinstance(data["pod_id"], str)
    assert isinstance(data["sku_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 0
    assert isinstance(data["quantity_reserved"], int)
    assert data["quantity_reserved"] >= 0
    assert isinstance(data["accessibility_rank"], int)
    assert data["accessibility_rank"] >= 1


def assert_pick_station(data: dict):
    _assert_common(data)
    assert isinstance(data["station_code"], str) and data["station_code"]
    assert isinstance(data["zone_id"], str)
    assert isinstance(data["max_queue"], int) and data["max_queue"] >= 1
    assert isinstance(data["queue_length"], int) and data["queue_length"] >= 0
    assert data["status"] in ("OPEN", "PAUSED", "CLOSED")


def assert_customer_order(data: dict):
    _assert_common(data)
    assert isinstance(data["order_code"], str) and data["order_code"]
    assert data["status"] in (
        "RECEIVED", "PLANNED", "IN_PROGRESS",
        "COMPLETE", "CANCELLED", "CUTOFF_MISSED",
    )
    assert isinstance(data["cutoff_at"], str)
    assert isinstance(data["priority"], int) and data["priority"] >= 0


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["sku_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["quantity_picked"], int) and data["quantity_picked"] >= 0


def assert_pick_task(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["line_id"], str)
    assert isinstance(data["pod_id"], str)
    assert isinstance(data["station_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in (
        "CREATED", "QUEUED", "DISPATCHED", "DELIVERED",
        "PICKING", "COMPLETE", "FAILED", "CANCELLED",
    )


def assert_stow_task(data: dict):
    _assert_common(data)
    assert isinstance(data["sku_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ("PENDING", "PLACED", "COMPLETE", "REJECTED")


def assert_charging_session(data: dict):
    _assert_common(data)
    assert isinstance(data["charger_id"], str)
    assert isinstance(data["drive_unit_id"], str)
    assert data["status"] in ("OPEN", "CLOSED", "ABORTED")


def assert_maintenance_window(data: dict):
    _assert_common(data)
    assert isinstance(data["drive_unit_id"], str)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "COMPLETE", "CANCELLED")
    assert data["kind"] in ("PREVENTIVE", "CORRECTIVE")


def assert_floor_exception(data: dict):
    _assert_common(data)
    assert data["kind"] in ("DROPPED_ITEM", "BLOCKED_PATH", "STRANDED_ROBOT")
    assert isinstance(data["zone_id"], str)
    assert data["status"] in (
        "OPEN", "TRIAGED_ROBOT", "TRIAGED_HUMAN", "RESOLVED",
    )


def assert_human_entry_permit(data: dict):
    _assert_common(data)
    assert isinstance(data["zone_id"], str)
    assert isinstance(data["exception_id"], str)
    assert data["status"] in ("REQUESTED", "ACTIVE", "RELEASED")


def assert_shift_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_date"], str)
    assert isinstance(data["staffed_pickers"], int) and data["staffed_pickers"] >= 0
    assert isinstance(data["planned_units"], int) and data["planned_units"] >= 0
    assert isinstance(data["projected_units"], int) and data["projected_units"] >= 0
    assert isinstance(data["feasible"], bool)


def assert_software_release(data: dict):
    _assert_common(data)
    assert isinstance(data["release_code"], str) and data["release_code"]
    assert data["status"] in (
        "DRAFT", "VALIDATING", "VALIDATED", "FAILED", "FLOOR_LIVE", "ROLLED_BACK",
    )
    assert isinstance(data["safety_check_passed"], bool)
