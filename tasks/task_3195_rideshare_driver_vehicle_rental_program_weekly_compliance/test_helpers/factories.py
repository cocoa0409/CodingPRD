"""Payload factories for every resource the programme creates."""
from typing import Optional

from .constants import TEST_DEFAULTS

# ─── Drivers ──────────────────────────────────────────

_DRIVER_SEQ = {"n": 0}
_VIN_SEQ = {"n": 0}
_PLATE_SEQ = {"n": 0}

_VIN_ALPHABET = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"


def _unique_vin(index: int) -> str:
    """A 17-character identification number, unique per call."""
    body = ""
    n = index
    for _ in range(14):
        body = _VIN_ALPHABET[n % len(_VIN_ALPHABET)] + body
        n //= len(_VIN_ALPHABET)
    return "1HG" + body


def create_driver_payload(**overrides) -> dict:
    """Registration payload for a driver record."""
    _DRIVER_SEQ["n"] += 1
    n = _DRIVER_SEQ["n"]
    defaults = {
        "full_name": f"Test Driver {n}",
        "email": f"driver{n}@example.com",
        "platform_driver_id": f"PLT-{n:08d}"[:12],
        "platform_activity_score": TEST_DEFAULTS["ACTIVITY_SCORE"],
        "driving_record_points": TEST_DEFAULTS["DRIVING_RECORD_POINTS"],
        "license_class": "FOR_HIRE",
        "program_driver_tier": "TIER_1",
    }
    defaults.update(overrides)
    return defaults


# ─── Enrollments ──────────────────────────────────────

def create_enrollment_payload(driver_id: str, **overrides) -> dict:
    """Enrolment request payload."""
    defaults = {"driver_id": driver_id, "program_tier": "TIER_1"}
    defaults.update(overrides)
    return defaults


# ─── Vehicles ─────────────────────────────────────────

def create_vehicle_payload(**overrides) -> dict:
    """Fleet-intake payload for a programme unit."""
    _VIN_SEQ["n"] += 1
    n = _VIN_SEQ["n"]
    defaults = {
        "vin": _unique_vin(n),
        "model_name": "Civic",
        "model_year": 2022,
        "vehicle_class": "STANDARD",
        "odometer_miles": TEST_DEFAULTS["ODOMETER_MILES"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
    }
    defaults.update(overrides)
    return defaults


# ─── Agreements ───────────────────────────────────────

def create_agreement_payload(enrollment_id: str, driver_id: str, vehicle_id: str,
                             **overrides) -> dict:
    """Rental agreement creation payload (metered shape by default)."""
    defaults = {
        "enrollment_id": enrollment_id,
        "driver_id": driver_id,
        "vehicle_id": vehicle_id,
        "weekly_rate_cents": TEST_DEFAULTS["WEEKLY_RATE_CENTS"],
        "insurance_premium_cents": TEST_DEFAULTS["INSURANCE_PREMIUM_CENTS"],
        "unlimited_mileage": False,
        "mileage_cap_miles": TEST_DEFAULTS["MILEAGE_CAP_MILES"],
        "maintenance_allowance_miles": TEST_DEFAULTS["MAINTENANCE_ALLOWANCE_MILES"],
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2027-08-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_unlimited_agreement_payload(enrollment_id: str, driver_id: str,
                                       vehicle_id: str, **overrides) -> dict:
    """Rental agreement creation payload with the unlimited-mile provision."""
    payload = create_agreement_payload(enrollment_id, driver_id, vehicle_id, **overrides)
    payload.pop("mileage_cap_miles", None)
    payload["unlimited_mileage"] = True
    return payload


# ─── Weeks ────────────────────────────────────────────

def open_week_payload(agreement_id: str, expected_agreement_version: int) -> dict:
    """Payload for opening the next weekly rental period."""
    return {
        "agreement_id": agreement_id,
        "expected_agreement_version": expected_agreement_version,
    }


def mileage_payload(miles_driven: int) -> dict:
    return {"miles_driven": miles_driven}


# ─── Maintenance events ───────────────────────────────

def create_maintenance_event_payload(agreement_id: str, vehicle_id: str,
                                     expected_vehicle_version: int,
                                     **overrides) -> dict:
    """Service-event report payload."""
    defaults = {
        "agreement_id": agreement_id,
        "vehicle_id": vehicle_id,
        "event_type": "UNSCHEDULED_REPAIR",
        "odometer_at_service": 41_200,
        "downtime_hours": 30,
        "damage_liability_cents": 0,
        "expected_vehicle_version": expected_vehicle_version,
    }
    defaults.update(overrides)
    return defaults


# ─── Payments ─────────────────────────────────────────

def tender_payload(amount_cents: int, payment_outcome: str = "SUCCEEDED",
                   expected_amount_due_cents: Optional[int] = None) -> dict:
    payload = {"amount_cents": amount_cents, "payment_outcome": payment_outcome}
    if expected_amount_due_cents is not None:
        payload["expected_amount_due_cents"] = expected_amount_due_cents
    return payload


# ─── Purchase options ─────────────────────────────────

def create_purchase_option_payload(agreement_id: str, driver_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "driver_id": driver_id,
        "purchase_price_cents": 1_800_000,
        "escrow_weeks_required": 24,
    }
    defaults.update(overrides)
    return defaults


# ─── Platform qualification checks ────────────────────

def create_platform_check_payload(agreement_id: str, vehicle_id: str) -> dict:
    return {"agreement_id": agreement_id, "vehicle_id": vehicle_id}


# ─── Fleet facts ──────────────────────────────────────

def create_fleet_fact_payload(**overrides) -> dict:
    defaults = {
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "demand_units": 3,
    }
    defaults.update(overrides)
    return defaults