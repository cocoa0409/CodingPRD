"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": _uniq("Z"),
        "grid_x": 0,
        "grid_y": 0,
        "width": 10,
        "height": 10,
        "max_human_occupancy": TEST_DEFAULTS["ZONE_MAX_HUMAN_OCCUPANCY"],
    }
    defaults.update(overrides)
    return defaults


def create_drive_unit_payload(home_zone_id, **overrides) -> dict:
    defaults = {"unit_code": _uniq("DU"), "home_zone_id": home_zone_id}
    defaults.update(overrides)
    return defaults


def create_charger_payload(zone_id, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "slot_count": TEST_DEFAULTS["CHARGER_SLOT_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_pod_payload(zone_id, **overrides) -> dict:
    defaults = {
        "pod_code": _uniq("P"),
        "zone_id": zone_id,
        "slot_capacity": TEST_DEFAULTS["POD_SLOT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_sku_payload(**overrides) -> dict:
    defaults = {"sku_code": _uniq("SKU"), "velocity_class": "LOW"}
    defaults.update(overrides)
    return defaults


def create_pick_station_payload(zone_id, **overrides) -> dict:
    defaults = {
        "station_code": _uniq("ST"),
        "zone_id": zone_id,
        "max_queue": TEST_DEFAULTS["STATION_MAX_QUEUE"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_order_payload(sku_id, **overrides) -> dict:
    lines = overrides.pop(
        "lines", [{"sku_id": sku_id, "quantity": 1}]
    )
    defaults = {
        "order_code": _uniq("O"),
        "cutoff_at": TEST_DEFAULTS["DEFAULT_CUTOFF"],
        "priority": 1,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_pick_task_payload(order_id, line_id, pod_id, station_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "line_id": line_id,
        "pod_id": pod_id,
        "station_id": station_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_stow_task_payload(sku_id, **overrides) -> dict:
    defaults = {"sku_id": sku_id, "quantity": 1}
    defaults.update(overrides)
    return defaults


def create_charging_session_payload(charger_id, drive_unit_id, **overrides) -> dict:
    defaults = {"charger_id": charger_id, "drive_unit_id": drive_unit_id}
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(drive_unit_id, **overrides) -> dict:
    defaults = {
        "drive_unit_id": drive_unit_id,
        "starts_at": "2026-09-01T10:00:00Z",
        "ends_at": "2026-09-01T11:00:00Z",
        "kind": "PREVENTIVE",
    }
    defaults.update(overrides)
    return defaults


def create_floor_exception_payload(zone_id, **overrides) -> dict:
    defaults = {"kind": "BLOCKED_PATH", "zone_id": zone_id}
    defaults.update(overrides)
    return defaults


def create_human_entry_permit_payload(zone_id, exception_id, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "exception_id": exception_id,
        "starts_at": "2026-09-01T08:30:00Z",
        "ends_at": "2026-09-01T09:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_shift_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_date": "2026-09-01",
        "staffed_pickers": 1,
        "planned_units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_software_release_payload(**overrides) -> dict:
    defaults = {"release_code": _uniq("1.0.")}
    defaults.update(overrides)
    return defaults
