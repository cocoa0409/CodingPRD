"""Payload factories — one per entity, input fields only."""
from .constants import DEFAULT_RATE_PERIOD

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


# ---------------------------------------------------------------------------
# Aircraft / documents / maintenance
# ---------------------------------------------------------------------------

def create_aircraft_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "tail_number": f"N{n:04d}CF",
        "aircraft_type": "LIGHT_JET",
        "passenger_capacity": 6,
        "home_base_icao": "KTEB",
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "doc_kind": "AIRWORTHINESS_CERT",
        "identifier": f"DOC-{n:04d}",
        "issued_at": "2025-01-01T00:00:00Z",
        "expires_at": "2027-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(**overrides) -> dict:
    defaults = {
        "window_start_utc": "2026-08-10T11:00:00Z",
        "window_end_utc": "2026-08-10T13:00:00Z",
        "maintenance_kind": "SCHEDULED_INSPECTION",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# People / money registries
# ---------------------------------------------------------------------------

def create_crew_member_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "employee_number": f"C{n:04d}",
        "full_name": f"Pilot {n}",
        "seat_qualification": "PIC",
        "type_ratings": ["LIGHT_JET"],
        "training_valid_until": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_business_unit_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "bu_code": f"BU-{n:04d}",
        "name": f"Business Unit {n}",
        "annual_flight_budget_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_passenger_profile_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "employee_number": f"E{n:04d}",
        "full_name": f"Passenger {n}",
        "priority_tier": "TIER_1",
        "sifl_control_employee": False,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Trips and legs
# ---------------------------------------------------------------------------

def create_trip_request_payload(requester_id, charge_bu_id, **overrides) -> dict:
    defaults = {
        "requester_id": requester_id,
        "charge_bu_id": charge_bu_id,
        "trip_kind": "BUSINESS",
        "purpose": "Client visit",
        "requested_departure_utc": "2026-08-10T12:00:00Z",
        "requested_return_utc": "2026-08-10T14:00:00Z",
        "passenger_ids": [requester_id],
    }
    defaults.update(overrides)
    return defaults


def create_flight_leg_payload(**overrides) -> dict:
    defaults = {
        "leg_sequence": 1,
        "origin_icao": "KTEB",
        "destination_icao": "KDCA",
        "scheduled_departure_utc": "2026-08-10T12:00:00Z",
        "scheduled_arrival_utc": "2026-08-10T14:00:00Z",
        "distance_statute_miles": 200,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

def create_catering_order_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": "SkyChefs",
        "menu_code": "VIP-1",
        "headcount": 1,
        "quoted_cost_cents": 25_000,
    }
    defaults.update(overrides)
    return defaults


def create_ground_transport_payload(**overrides) -> dict:
    defaults = {
        "provider_name": "ExecuCar",
        "pickup_minutes_after_arrival": 15,
        "quoted_cost_cents": 12_000,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Charter and rate periods
# ---------------------------------------------------------------------------

def create_charter_supplement_payload(trip_request_id, **overrides) -> dict:
    defaults = {
        "trip_request_id": trip_request_id,
        "vendor_name": "CharterCo",
        "quoted_cost_cents": 1_200_000,
        "aircraft_type_offered": "LIGHT_JET",
    }
    defaults.update(overrides)
    return defaults


def create_sifl_rate_period_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_RATE_PERIOD)
    defaults.update(overrides)
    return defaults
