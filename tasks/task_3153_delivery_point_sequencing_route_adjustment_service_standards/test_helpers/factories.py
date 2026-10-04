"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "FACILITY_CODE": "LAX",
    "UNIT_CODE": "DU1",
    "OFFICE_NAME": "Test Station",
    "ADDRESS_LINE1": "1 Test St",
    "CITY": "Culver City",
    "STATE_CODE": "CA",
    "ROUTE_CODE": "C001",
    "ROUTE_TYPE": "CITY",
    "CARRIER_NAME": "Test Carrier",
    "POINT_KIND": "RESIDENTIAL",
    "NEW_ADDRESS_LINE1": "1 Forward Rd",
    "NEW_CITY": "Reno",
    "NEW_STATE_CODE": "NV",
}


def create_facility_payload(**overrides) -> dict:
    payload = {
        "facility_code": DEFAULTS["FACILITY_CODE"],
        "facility_type": TEST_DEFAULTS["FACILITY_TYPE"],
        "region_class": TEST_DEFAULTS["REGION_CLASS"],
        "dispatch_cutoff_local": TEST_DEFAULTS["DISPATCH_CUTOFF"],
        "operating_days": list(TEST_DEFAULTS["OPERATING_DAYS"]),
    }
    payload.update(overrides)
    return payload


def create_unit_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "unit_code": DEFAULTS["UNIT_CODE"],
        "office_name": DEFAULTS["OFFICE_NAME"],
        "delivery_office_facility_id": facility_id,
        "case_slot_count_per_route": TEST_DEFAULTS["CASE_SLOT_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_point_payload(zip11: str, **overrides) -> dict:
    payload = {
        "address_line1": DEFAULTS["ADDRESS_LINE1"],
        "city": DEFAULTS["CITY"],
        "state_code": DEFAULTS["STATE_CODE"],
        "zip11": zip11,
        "point_kind": DEFAULTS["POINT_KIND"],
    }
    payload.update(overrides)
    return payload


def create_carrier_payload(employee_id: str, **overrides) -> dict:
    payload = {
        "employee_id": employee_id,
        "full_name": DEFAULTS["CARRIER_NAME"],
        "carrier_class": "REGULAR",
    }
    payload.update(overrides)
    return payload


def create_route_payload(carrier_id: str, **overrides) -> dict:
    payload = {
        "route_code": DEFAULTS["ROUTE_CODE"],
        "assigned_carrier_id": carrier_id,
        "route_type": DEFAULTS["ROUTE_TYPE"],
    }
    payload.update(overrides)
    return payload


def create_evaluation_payload(expected_route_version: int, **overrides) -> dict:
    payload = {
        "evaluation_kind": "MINI_SURVEY",
        "count_week_start": "2026-09-19",
        "expected_route_version": expected_route_version,
    }
    payload.update(overrides)
    return payload


def submit_counts_payload(**overrides) -> dict:
    payload = {
        "letters_count_total": 3600,
        "flats_count_total": 900,
        "parcels_count_total": 40,
        "actual_street_minutes_total": 2160,
        "office_minutes_total": 1440,
    }
    payload.update(overrides)
    return payload


def create_adjustment_payload(**overrides) -> dict:
    payload = {
        "proposed_evaluated_minutes": 545,
        "points_transferred_out": [],
        "effective_date": "2026-09-10",
    }
    payload.update(overrides)
    return payload


def create_auxiliary_payload(helper_carrier_id: str, service_date: str, **overrides) -> dict:
    payload = {
        "helper_carrier_id": helper_carrier_id,
        "service_date": service_date,
        "projected_overrun_minutes": 60,
        "seasonal_surge_flag": False,
    }
    payload.update(overrides)
    return payload


def create_coa_payload(old_delivery_point_id: str, **overrides) -> dict:
    payload = {
        "old_delivery_point_id": old_delivery_point_id,
        "new_address_line1": DEFAULTS["NEW_ADDRESS_LINE1"],
        "new_city": DEFAULTS["NEW_CITY"],
        "new_state_code": DEFAULTS["NEW_STATE_CODE"],
        "new_zip11": "89501000100",
        "move_kind": "FAMILY",
        "move_type": "TEMPORARY",
        "begin_date": "2026-09-01",
        "end_date": "2026-10-01",
    }
    payload.update(overrides)
    return payload


def create_hold_payload(delivery_point_id: str, **overrides) -> dict:
    payload = {
        "delivery_point_id": delivery_point_id,
        "hold_start_date": "2026-09-10",
        "hold_end_date": "2026-09-12",
        "disposition": "ACCUMULATE_DELIVER_ON_END",
    }
    payload.update(overrides)
    return payload


def create_rule_payload(dest_facility_id: str, expected_facility_version: int,
                        **overrides) -> dict:
    payload = {
        "dest_facility_id": dest_facility_id,
        "mail_class": "FIRST_CLASS",
        "service_days": 2,
        "effective_from": "2026-01-01",
        "expected_facility_version": expected_facility_version,
    }
    payload.update(overrides)
    return payload


def create_service_query_payload(origin_facility_id: str, dest_facility_id: str,
                                 **overrides) -> dict:
    payload = {
        "origin_facility_id": origin_facility_id,
        "dest_facility_id": dest_facility_id,
        "mail_class": "FIRST_CLASS",
        "acceptance_date": "2026-09-01",
        "acceptance_time_local": "10:00",
    }
    payload.update(overrides)
    return payload


def create_scan_payload(delivery_point_id: str, carrier_id: str, **overrides) -> dict:
    payload = {
        "delivery_point_id": delivery_point_id,
        "carrier_id": carrier_id,
        "scan_code": "DELIVERED",
        "scan_datetime": "2026-09-01T12:00:00Z",
        "gps_within_geofence": True,
    }
    payload.update(overrides)
    return payload


def create_inquiry_payload(delivery_point_id: str, **overrides) -> dict:
    payload = {
        "delivery_point_id": delivery_point_id,
        "inquiry_kind": "MISSING_MAIL",
        "opened_by_channel": "WEB",
    }
    payload.update(overrides)
    return payload
