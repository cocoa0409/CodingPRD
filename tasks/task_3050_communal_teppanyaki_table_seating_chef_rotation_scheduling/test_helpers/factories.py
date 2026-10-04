"""Payload factories: one per resource family, input fields only."""
from .constants import TIER_ROWS, TEST_DEFAULTS


def create_venue_payload(**overrides) -> dict:
    payload = {
        "venue_name": TEST_DEFAULTS["VENUE_NAME"],
        "city_code": TEST_DEFAULTS["CITY_CODE"],
        "ventilation_zone": TEST_DEFAULTS["VENTILATION_ZONE"],
    }
    payload.update(overrides)
    return payload


def create_party_payload(venue_id, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "lead_guest_name": "Dana Whitfield",
        "contact_phone": "212-555-0141",
    }
    payload.update(overrides)
    return payload


def create_tier_payload(venue_id, tier_code="T6", **overrides) -> dict:
    row = dict(TIER_ROWS.get(tier_code, TIER_ROWS["T6"]))
    payload = {"venue_id": venue_id}
    payload.update(row)
    payload.update(overrides)
    return payload


def create_table_payload(venue_id, tier_code="T6", seat_capacity=6, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "tier_code": tier_code,
        "seat_capacity": seat_capacity,
    }
    payload.update(overrides)
    return payload


def create_chef_payload(venue_id, chef_name="Kenji Ito", station_zone="ZONE_A", **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "chef_name": chef_name,
        "station_zone": station_zone,
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(venue_id, party_id, tier_id, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "party_id": party_id,
        "tier_id": tier_id,
        "party_size": 4,
        "scheduled_time": TEST_DEFAULTS["SCHEDULED_TIME"],
        "payment_mode": TEST_DEFAULTS["PAYMENT_MODE"],
    }
    payload.update(overrides)
    return payload


def create_maintenance_window_payload(venue_id, maintenance_kind="GRILL_REBUILD", **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "maintenance_kind": maintenance_kind,
        "planned_start_at": "2026-09-03T11:00:00Z",
        "planned_end_at": "2026-09-03T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_sushi_ticket_payload(venue_id, reservation_id, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "reservation_id": reservation_id,
        "item_code": "CALIFORNIA-ROLL",
        "quantity": 2,
        "requested_at": "2026-09-03T19:05:00Z",
        "unit_price_cents": 1600,
    }
    payload.update(overrides)
    return payload