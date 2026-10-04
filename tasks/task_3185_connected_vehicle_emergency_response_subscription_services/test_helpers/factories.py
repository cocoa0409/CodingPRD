"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def make_vin(seed: int) -> str:
    """17-char uppercase alnum VIN excluding I/O/Q."""
    tail = f"{seed:05d}"[-5:]
    return f"1G1ZD5ST5JF{tail}"[-17:].rjust(17, "1")


def create_plan_tier_payload(**overrides) -> dict:
    defaults = {
        "code": "SAFETY",
        "monthly_fee_cents": 2000,
        "allows_emergency": True,
        "allows_remote_commands": False,
        "allows_navigation": False,
        "allows_data_gb": 0,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Test Owner {n}",
        "email": f"owner{n}@example.com",
        "phone": f"+1512555{n:04d}",
        "home_region_code": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_coverage_zone_payload(**overrides) -> dict:
    defaults = {
        "region_code": "TX",
        "has_cellular": True,
        "supports_data": True,
        "supports_navigation": True,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "vin": make_vin(_n()),
        "make": "Chevrolet",
        "model": "Malibu",
        "model_year": 2020,
        "region_code": "TX",
        "hardware_generation": 5,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(**overrides) -> dict:
    defaults = {
        "vehicle_id": "",
        "tier_code": "SAFETY",
    }
    defaults.update(overrides)
    return defaults


def create_crash_event_payload(**overrides) -> dict:
    defaults = {
        "delta_v_kph": 70,
        "rollover_detected": False,
        "airbag_deployed": True,
        "location_region_code": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_psap_payload(**overrides) -> dict:
    defaults = {
        "name": f"Test PSAP {_n()}",
        "region_code": "TX",
        "accepts_location_transfer": True,
    }
    defaults.update(overrides)
    return defaults


def create_stolen_case_payload(**overrides) -> dict:
    defaults = {
        "police_report_number": f"TX-2026-{_n():04d}",
        "reporting_agency": "Austin PD",
    }
    defaults.update(overrides)
    return defaults


def create_remote_command_payload(**overrides) -> dict:
    defaults = {"command_type": "LOCK"}
    defaults.update(overrides)
    return defaults


def create_diagnostic_report_payload(**overrides) -> dict:
    defaults = {
        "odometer_km": 10000 + _n(),
        "engine_hours": 400,
        "dtc_codes": [],
        "oil_life_pct": 90,
    }
    defaults.update(overrides)
    return defaults


def create_dealer_payload(**overrides) -> dict:
    defaults = {
        "name": f"Test Dealer {_n()}",
        "region_code": "TX",
        "service_capacity_per_day": 2,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(**overrides) -> dict:
    defaults = {
        "vehicle_id": "",
        "diagnostic_report_id": "",
        "scheduled_date": "2026-09-10",
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(**overrides) -> dict:
    defaults = {"consent_type": "DRIVING_DATA_COLLECTION"}
    defaults.update(overrides)
    return defaults
