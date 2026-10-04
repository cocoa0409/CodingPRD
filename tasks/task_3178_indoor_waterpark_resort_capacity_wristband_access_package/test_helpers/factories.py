"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_resort_payload(**overrides) -> dict:
    payload = {
        "name": "Sandusky",
        "park_capacity_occupancy_units": TEST_DEFAULTS["PARK_CAPACITY_OCCUPANCY_UNITS"],
        "day_pass_cap_units": TEST_DEFAULTS["DAY_PASS_CAP_UNITS"],
        "arcade_credit_rate_cents_per_unit": TEST_DEFAULTS["ARCADE_CREDIT_RATE_CENTS_PER_UNIT"],
    }
    payload.update(overrides)
    return payload


def create_room_type_payload(**overrides) -> dict:
    payload = {
        "code": TEST_DEFAULTS["ROOM_TYPE_CODE"],
        "max_occupancy": TEST_DEFAULTS["MAX_OCCUPANCY"],
        "base_rate_cents": TEST_DEFAULTS["BASE_RATE_CENTS"],
        "is_cabana": False,
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(room_type_id: str, **overrides) -> dict:
    payload = {
        "room_type_id": room_type_id,
        "guest_count": 2,
        "arrival_date": TEST_DEFAULTS["DOMESTIC_SERVICE_DATE"],
        "departure_date": TEST_DEFAULTS["SERVICE_DATE_END"],
    }
    payload.update(overrides)
    return payload


def create_day_pass_payload(expected_resort_version: int, **overrides) -> dict:
    payload = {
        "service_date": TEST_DEFAULTS["DOMESTIC_SERVICE_DATE"],
        "units_requested": 2,
        "expected_resort_version": expected_resort_version,
    }
    payload.update(overrides)
    return payload


def create_wristband_payload(holder_type: str, owner_name: str, **overrides) -> dict:
    payload = {"holder_type": holder_type, "owner_name": owner_name}
    payload.update(overrides)
    return payload


def create_attraction_payload(**overrides) -> dict:
    payload = {"name": "Bear Track", "min_occupancy_units": 1, "required_certification": "NONE"}
    payload.update(overrides)
    return payload


def create_lifeguard_shift_payload(attraction_id: str, staffer_name: str, **overrides) -> dict:
    payload = {
        "attraction_id": attraction_id,
        "staffer_name": staffer_name,
        "certification_code": "LIFEGUARD",
        "shift_date": TEST_DEFAULTS["DOMESTIC_SERVICE_DATE"],
        "start_minute": 540,
        "end_minute": 660,
        "rotation_minutes": 60,
    }
    payload.update(overrides)
    return payload


def create_water_quality_log_payload(attraction_id: str, **overrides) -> dict:
    payload = {
        "attraction_id": attraction_id,
        "sampled_at": "2026-09-03T09:00:00Z",
        "ph_reading": 7.4,
        "free_chlorine_ppm": 2.0,
        "turbidity_ntu": 0.3,
    }
    payload.update(overrides)
    return payload


def create_admission_payload(wristband_id: str, **overrides) -> dict:
    payload = {
        "wristband_id": wristband_id,
        "service_date": TEST_DEFAULTS["DOMESTIC_SERVICE_DATE"],
        "direction": "IN",
    }
    payload.update(overrides)
    return payload


def create_cabana_payload(**overrides) -> dict:
    payload = {"cabana_label": "CAB-1", "cabana_kind": "CABANA", "capacity_units": 4}
    payload.update(overrides)
    return payload


def create_cabana_booking_payload(cabana_id: str, group_booking_id: str, expected_cabana_version: int,
                                  **overrides) -> dict:
    payload = {
        "cabana_id": cabana_id,
        "group_booking_id": group_booking_id,
        "service_date": TEST_DEFAULTS["DOMESTIC_SERVICE_DATE"],
        "start_minute": 600,
        "end_minute": 720,
        "member_units": 2,
        "expected_cabana_version": expected_cabana_version,
    }
    payload.update(overrides)
    return payload


def create_group_booking_payload(**overrides) -> dict:
    payload = {
        "group_kind": "BIRTHDAY",
        "service_date": TEST_DEFAULTS["DOMESTIC_SERVICE_DATE"],
        "member_count": 2,
    }
    payload.update(overrides)
    return payload


def create_group_member_payload(group_booking_id: str, member_name: str, **overrides) -> dict:
    payload = {"group_booking_id": group_booking_id, "member_name": member_name, "member_units": 1}
    payload.update(overrides)
    return payload


def create_group_deposit_payload(amount_cents: int, external_payment_ref: str, **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "external_payment_ref": external_payment_ref}
    payload.update(overrides)
    return payload


def create_activity_session_payload(**overrides) -> dict:
    payload = {"name": "Craft Hour", "tier_code": "STANDARD", "base_price_cents": 3500, "capacity_units": 20}
    payload.update(overrides)
    return payload


def create_activity_booking_payload(activity_session_id: str, group_booking_id: str, **overrides) -> dict:
    payload = {
        "activity_session_id": activity_session_id,
        "group_booking_id": group_booking_id,
        "attendees": 2,
    }
    payload.update(overrides)
    return payload


def create_arcade_grant_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_manager_payload(async_role: str, async_name: str, **overrides) -> dict:
    payload = {"async_role": async_role, "async_name": async_name}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def simulate_payment_payload(group_booking_id: str, outcome: str = "ACCEPTED", **overrides) -> dict:
    payload = {"group_booking_id": group_booking_id, "outcome": outcome}
    payload.update(overrides)
    return payload