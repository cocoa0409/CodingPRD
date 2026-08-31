"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS

DEFAULTS = {
    "DOCK_NAME": "Pier One",
    "STOP_NAME": "Ferry Landing",
    "VESSEL_NAME": "Osprey",
    "CREW_NAME": "K. Rowe",
}


def create_dock_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["DOCK_NAME"],
        "berth_count": 2,
        "min_turnaround_minutes": 15,
        "landing_fee_per_pax_cents": 120,
        "berth_minute_rate_cents": 40,
        "monthly_fee_cap_cents": 1_000_000,
    }
    payload.update(overrides)
    return payload


def create_stop_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["STOP_NAME"],
        "zone_index": 1,
        "charted_depth_m": 3.50,
    }
    payload.update(overrides)
    return payload


def create_vessel_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["VESSEL_NAME"],
        "seat_capacity": 40,
        "draft_m": 1.20,
        "hull_class": "OFFSHORE",
        "required_endorsement": "MASTER_25T",
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(**overrides) -> dict:
    payload = {
        "inspection_type": "ANNUAL",
        "result": "PASS",
        "deficiency_count": 0,
        "performed_on": TEST_DEFAULTS["ANNUAL_PERFORMED_ON"],
    }
    payload.update(overrides)
    return payload


def create_crew_member_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["CREW_NAME"],
        "endorsement_class": "MASTER_100T",
        "cert_expires_on": TEST_DEFAULTS["CERT_EXPIRES_ON"],
        "medical_expires_on": TEST_DEFAULTS["MEDICAL_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def create_service_day_payload(**overrides) -> dict:
    payload = {
        "service_date": TEST_DEFAULTS["SERVICE_DATE"],
        "wind_knots": 10.0,
        "wave_height_m": 0.30,
        "low_water_m": 2.10,
    }
    payload.update(overrides)
    return payload


def create_trip_payload(service_day_id, vessel_id, master_crew_id, origin_stop_id,
                        destination_stop_id, **overrides) -> dict:
    payload = {
        "service_day_id": service_day_id,
        "vessel_id": vessel_id,
        "master_crew_id": master_crew_id,
        "origin_stop_id": origin_stop_id,
        "destination_stop_id": destination_stop_id,
        "service_mode": "SCHEDULED",
        "scheduled_departure_utc": "2026-09-12T14:00:00Z",
        "scheduled_arrival_utc": "2026-09-12T14:25:00Z",
    }
    payload.update(overrides)
    return payload


def create_dock_slot_payload(dock_id, expected_dock_version, **overrides) -> dict:
    payload = {
        "dock_id": dock_id,
        "purpose": "LANDING",
        "start_utc": "2026-09-12T14:00:00Z",
        "end_utc": "2026-09-12T14:20:00Z",
        "expected_dock_version": expected_dock_version,
    }
    payload.update(overrides)
    return payload


def create_ride_pass_payload(**overrides) -> dict:
    payload = {
        "zone_tier": "INNER",
        "rides_purchased": 10,
        "purchase_price_cents": 9000,
        "valid_until": TEST_DEFAULTS["PASS_VALID_UNTIL"],
    }
    payload.update(overrides)
    return payload


def create_booking_payload(origin_stop_id, destination_stop_id, **overrides) -> dict:
    payload = {
        "origin_stop_id": origin_stop_id,
        "destination_stop_id": destination_stop_id,
        "requested_date": TEST_DEFAULTS["SERVICE_DATE"],
        "service_mode": "SCHEDULED",
        "party_size": 1,
    }
    payload.update(overrides)
    return payload


def create_interruption_payload(**overrides) -> dict:
    payload = {"cause": "WEATHER"}
    payload.update(overrides)
    return payload


def refund_pass_payload(settlement_basis="PRO_RATA") -> dict:
    return {"settlement_basis": settlement_basis}


def approve_claim_payload(decision="APPROVE") -> dict:
    return {"decision": decision}


def board_payload(boarded_booking_ids) -> dict:
    return {"boarded_booking_ids": list(boarded_booking_ids)}


def confirm_payload(expected_trip_version) -> dict:
    return {"expected_trip_version": expected_trip_version}


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
