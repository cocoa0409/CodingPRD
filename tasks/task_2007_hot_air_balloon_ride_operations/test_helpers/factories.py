"""Payload factories — one per creatable entity, input fields only (PRD §3/§4)."""
from .constants import DEFAULTS, FLIGHT_RULES

_COUNTER = {"n": 0}


def _seq() -> int:
    _COUNTER["n"] += 1
    return _COUNTER["n"]


def create_launch_site_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Rio Grande North {n}",
        "surface_wind_limit_kts": 8,
        "aloft_wind_limit_kts": 20,
        "per_use_fee_cents": 15000,
        "permission_expires_on": DEFAULTS["PERMISSION_EXPIRES"],
    }
    defaults.update(overrides)
    return defaults


def create_balloon_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "registration": f"N{n:03d}AB",
        "basket_capacity_passengers": 6,
        "max_gross_weight_lbs": 1400,
        "empty_weight_lbs": 600,
    }
    defaults.update(overrides)
    return defaults


def create_pilot_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Pat Harwell {n}",
        "certificate_number": f"PC-{2200 + n}",
        "medical_expires_on": DEFAULTS["MEDICAL_EXPIRES"],
        "external_pic_hours_180d": 20.0,
        "external_takeoffs_landings_90d": 5,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Cara Diaz {n}",
        "email": f"customer{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_flight_payload(launch_site_id, balloon_id, pilot_id, **overrides) -> dict:
    defaults = {
        "scheduled_date": DEFAULTS["FLIGHT_DATE"],
        "dawn_window_start": DEFAULTS["DAWN_START"],
        "dawn_window_end": DEFAULTS["DAWN_END"],
        "launch_site_id": launch_site_id,
        "balloon_id": balloon_id,
        "pilot_id": pilot_id,
        "kind": "SHARED",
        "fuel_lbs": FLIGHT_RULES["DEFAULT_FUEL_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "party_size": 1,
        "declared_weight_lbs": 180,
        "photo_package_tier": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_passenger_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Passenger {n}",
        "weight_lbs": 180,
        "is_minor": False,
    }
    defaults.update(overrides)
    return defaults


def create_weather_briefing_payload(**overrides) -> dict:
    """Defaults describe calm, GO-worthy dawn conditions for the default site
    (surface limit 8, aloft limit 20, visibility >= 3.0, no precipitation)."""
    defaults = {
        "surface_wind_kts": 4,
        "aloft_wind_kts": 10,
        "visibility_mi": 10.0,
        "precipitation": False,
    }
    defaults.update(overrides)
    return defaults


def create_chase_assignment_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "crew_lead_name": f"Dee Chavez {n}",
        "vehicle_id": f"TRUCK-{n}",
        "crew_size": 3,
    }
    defaults.update(overrides)
    return defaults
