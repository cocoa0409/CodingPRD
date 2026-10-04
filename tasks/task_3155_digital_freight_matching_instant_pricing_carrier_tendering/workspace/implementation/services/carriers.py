"""Carrier onboarding, the eligibility gate and the suspension cascade."""

from constants import (
    MAX_SAFETY_SCORE, MIN_CARGO_COVERAGE_CENTS, MIN_INSURANCE_LIABILITY_CENTS,
    RISK_ELIGIBILITY_FLOOR, d, utc,
)
from db import clock_now, db, touch
from errors import ApiError
from services.common import refresh_carrier_score


def apply_carrier_attribute(carrier, field, value):
    carrier[field] = value


# --------------------------------------------------------------------------
# The insurance cascade (PRD 3.10) — four mutations deep.
# --------------------------------------------------------------------------
def unwind_carrier_bookings(carrier):
    """Every live booking is cancelled, its unit freed and its load reopened."""
    cancelled = []
    for booking in list(db.bookings.values()):
        if booking["carrier_id"] != carrier["id"]:
            continue
        if booking["status"] not in ("PENDING_APPOINTMENT", "IN_TRANSIT"):
            continue
        booking["status"] = "CANCELLED"
        touch(booking)
        equipment = db.equipment.get(booking["equipment_id"])
        if equipment is not None and equipment["status"] == "ASSIGNED":
            equipment["status"] = "AVAILABLE"
            touch(equipment)
        load = db.loads.get(booking["load_id"])
        if load is not None:
            load["status"] = "UNCOVERED"
            load["carrier_id"] = None
            load["equipment_id"] = None
            touch(load)
        cancelled.append(booking["id"])
    return cancelled


def sync_carrier(carrier):
    """Suspends a VERIFIED carrier whose certificate has lapsed (PRD 3.10)."""
    if carrier["status"] != "VERIFIED":
        return False
    expires = carrier.get("insurance_expires_at")
    if expires is None:
        return False
    if utc(expires) <= clock_now():
        carrier["status"] = "SUSPENDED"
        carrier["suspension_reason"] = "INSURANCE_EXPIRED"
        touch(carrier)
        unwind_carrier_bookings(carrier)
        return True
    return False


def sync_all_carriers():
    suspended = []
    for carrier in list(db.carriers.values()):
        if sync_carrier(carrier):
            suspended.append(carrier["id"])
    return suspended


# --------------------------------------------------------------------------
# The eligibility gate (PRD 2.10) — first failing clause determines the error.
# --------------------------------------------------------------------------
def carrier_eligibility_gate(carrier, load, shipper):
    sync_carrier(carrier)
    if carrier["status"] != "VERIFIED":
        raise ApiError("ERR_CARRIER_NOT_VERIFIED")
    if carrier["operating_authority_status"] == "REVOKED":
        raise ApiError("ERR_AUTHORITY_REVOKED")
    if float(carrier["operational_risk_score"]) < float(RISK_ELIGIBILITY_FLOOR):
        raise ApiError("ERR_CARRIER_RISK_BLOCKED")
    expires = carrier.get("insurance_expires_at")
    if expires is None or not utc(expires) > clock_now():
        raise ApiError("ERR_INSURANCE_EXPIRED")
    if carrier["id"] in (shipper.get("blocked_carrier_ids") or []):
        raise ApiError("ERR_CARRIER_BLOCKED")
    if load["equipment_type"] not in (carrier.get("equipment_types") or []):
        raise ApiError("ERR_EQUIPMENT_UNAVAILABLE")


# --------------------------------------------------------------------------
# Onboarding steps
# --------------------------------------------------------------------------
def verify_authority(carrier):
    if carrier["operating_authority_status"] == "REVOKED":
        raise ApiError("ERR_AUTHORITY_REVOKED")
    mc_number = carrier.get("mc_number")
    if not mc_number:
        raise ApiError("ERR_DUPLICATE_MC_NUMBER")
    duplicates = [c for c in db.carriers.values()
                  if c["id"] != carrier["id"] and c.get("mc_number") == mc_number]
    if duplicates:
        raise ApiError("ERR_DUPLICATE_MC_NUMBER")
    if carrier["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")
    carrier["status"] = "AUTHORITY_VERIFIED"
    carrier["operating_authority_status"] = "ACTIVE"
    carrier["authority_verified_at"] = clock_now()
    touch(carrier)
    return carrier


def attest_insurance(carrier, expires_at, liability_limit_cents, cargo_limit_cents,
                     certificate_reference=None):
    if carrier["status"] != "AUTHORITY_VERIFIED":
        raise ApiError("ERR_INVALID_STATE")
    if not utc(expires_at) > clock_now():
        raise ApiError("ERR_INSURANCE_EXPIRED")
    if int(liability_limit_cents) < MIN_INSURANCE_LIABILITY_CENTS:
        raise ApiError("ERR_INSURANCE_LIMIT_BELOW_MINIMUM")
    if int(cargo_limit_cents) < MIN_CARGO_COVERAGE_CENTS:
        raise ApiError("ERR_CARGO_COVERAGE_BELOW_MINIMUM")
    carrier["insurance_expires_at"] = utc(expires_at)
    carrier["insurance_liability_limit_cents"] = int(liability_limit_cents)
    carrier["cargo_coverage_limit_cents"] = int(cargo_limit_cents)
    if certificate_reference is not None:
        carrier["certificate_reference"] = certificate_reference
    carrier["status"] = "INSURANCE_ON_FILE"
    carrier["insurance_attested_at"] = clock_now()
    touch(carrier)
    return carrier


def verify_safety(carrier, safety_score=None):
    if carrier["status"] != "INSURANCE_ON_FILE":
        raise ApiError("ERR_INVALID_STATE")
    score = safety_score if safety_score is not None else carrier.get("safety_score")
    if score is None:
        raise ApiError("ERR_INVALID_REQUEST", "safety_score is required.")
    if d(score) > MAX_SAFETY_SCORE:
        raise ApiError("ERR_SAFETY_SCORE_TOO_LOW")
    available = [unit for unit in db.equipment.values()
                 if unit["carrier_id"] == carrier["id"] and unit["status"] == "AVAILABLE"]
    if not available:
        raise ApiError("ERR_NO_EQUIPMENT_ON_FILE")
    carrier["safety_score"] = float(score)
    carrier["status"] = "VERIFIED"
    touch(carrier)
    return carrier


def suspend_carrier(carrier, reason_code):
    if carrier["status"] == "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE")
    if reason_code is None or reason_code == "":
        raise ApiError("ERR_INVALID_REQUEST", "reason_code is required.")
    carrier["status"] = "SUSPENDED"
    carrier["suspension_reason"] = reason_code
    touch(carrier)
    unwind_carrier_bookings(carrier)
    return carrier


def reinstate_carrier(carrier):
    if carrier["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE")
    expires = carrier.get("insurance_expires_at")
    if expires is None or not utc(expires) > clock_now():
        raise ApiError("ERR_INSURANCE_EXPIRED")
    if int(carrier.get("insurance_liability_limit_cents") or 0) < MIN_INSURANCE_LIABILITY_CENTS:
        raise ApiError("ERR_INSURANCE_LIMIT_BELOW_MINIMUM")
    if int(carrier.get("cargo_coverage_limit_cents") or 0) < MIN_CARGO_COVERAGE_CENTS:
        raise ApiError("ERR_CARGO_COVERAGE_BELOW_MINIMUM")
    carrier["status"] = "INSURANCE_ON_FILE"
    carrier["suspension_reason"] = None
    carrier["insurance_attested_at"] = clock_now()
    touch(carrier)
    return carrier