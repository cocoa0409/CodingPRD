"""Payload factories — one per entity, client-supplied input fields only."""

from .constants import (
    CLOCK_START,
    DEFAULT_BATTERY_PCT,
    DEFAULT_TEMP_BUDGET_CENTS_PER_DAY,
    DEFAULT_TOUR_DURATION_MINUTES,
    TEST_DEFAULTS,
)

DEFAULTS = {
    "PROPERTY_NAME": "Cedar Park",
    "ADDRESS_LINE": "1 Cedar Way",
    "UNIT_CAPACITY": TEST_DEFAULTS["UNIT_CAPACITY"],
    "TEMP_BUDGET_CENTS_PER_DAY": TEST_DEFAULTS["TEMP_BUDGET_CENTS_PER_DAY"],
    "BUILDING_NAME": "B-1",
    "BUILDING_RSSI_DBM": TEST_DEFAULTS["BUILDING_RSSI_DBM"],
    "NETWORK_DESIGN": TEST_DEFAULTS["NETWORK_DESIGN"],
    "UNIT_NUMBER": "U-101",
    "FIRMWARE_VERSION": "LATEST",
    "FULL_NAME": "Test Resident",
    "EMAIL": "resident@example.com",
    "TECHNICIAN_ID": "tech-field-1",
    "PROSPECT_NAME": "Test Prospect",
    "PROSPECT_ID_DOCUMENT": "DL-TEST-1",
    "GUEST_LABEL": "Guest",
    "VISIT_START_AT": "2026-09-03T10:00:00Z",
    "VISIT_END_AT": "2026-09-03T12:00:00Z",
}


def create_property_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROPERTY_NAME"],
        "address_line": DEFAULTS["ADDRESS_LINE"],
        "unit_capacity": DEFAULTS["UNIT_CAPACITY"],
        "temp_budget_cents_per_day": DEFAULTS["TEMP_BUDGET_CENTS_PER_DAY"],
    }
    defaults.update(overrides)
    return defaults


def create_building_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["BUILDING_NAME"],
        "network_design": DEFAULTS["NETWORK_DESIGN"],
        "wifi_rssi_dbm": DEFAULTS["BUILDING_RSSI_DBM"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {"unit_number": DEFAULTS["UNIT_NUMBER"]}
    defaults.update(overrides)
    return defaults


def create_device_payload(**overrides) -> dict:
    defaults = {
        "device_type": "SMART_LOCK",
        "firmware_version": DEFAULTS["FIRMWARE_VERSION"],
        "battery_pct": DEFAULT_BATTERY_PCT,
    }
    defaults.update(overrides)
    return defaults


def create_resident_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "email": DEFAULTS["EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_guest_pass_payload(**overrides) -> dict:
    defaults = {
        "guest_label": DEFAULTS["GUEST_LABEL"],
        "start_at": "2026-09-05T09:00:00Z",
        "end_at": "2026-09-06T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_tour_session_payload(**overrides) -> dict:
    defaults = {
        "prospect_name": DEFAULTS["PROSPECT_NAME"],
        "prospect_id_document": DEFAULTS["PROSPECT_ID_DOCUMENT"],
        "requested_start_at": "2026-09-02T15:00:00Z",
        "duration_minutes": DEFAULT_TOUR_DURATION_MINUTES,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_visit_payload(**overrides) -> dict:
    defaults = {
        "technician_id": DEFAULTS["TECHNICIAN_ID"],
        "start_at": DEFAULTS["VISIT_START_AT"],
        "end_at": DEFAULTS["VISIT_END_AT"],
        "is_emergency": False,
    }
    defaults.update(overrides)
    return defaults


def create_installation_job_payload(**overrides) -> dict:
    defaults = {
        "device_type": "SMART_LOCK",
        "requires_resident_coordination": False,
        "access_window_start": "2026-09-03T09:00:00Z",
        "access_window_end": "2026-09-03T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(**overrides) -> dict:
    defaults = {"assigned_technician_id": DEFAULTS["TECHNICIAN_ID"]}
    defaults.update(overrides)
    return defaults


def certify_notice_payload(**overrides) -> dict:
    defaults = {"notice_mailed_at": f"{CLOCK_START[:11]}09:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_deactivate_payload(**overrides) -> dict:
    defaults = {"notice_end_at": "2026-09-20T00:00:00Z"}
    defaults.update(overrides)
    return defaults