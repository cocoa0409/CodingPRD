"""Facility registration, read, and biennial renewal (PRD section 3.1).

Facility state machine: REGISTERED -> EXPIRED (clock sweep, strict <),
REGISTERED -> REGISTERED / EXPIRED -> REGISTERED (renew, OCC-guarded),
REGISTERED -> SUSPENDED (inspection-refusal cascade; absorbing).
"""
from datetime import timedelta

from flask import Blueprint

import db
import serialize
import services
from auth import require_roles, ALL_ROLES
from envelope import ok, json_body
from errors import ApiError

bp = Blueprint("facilities", __name__)

FACILITY_KINDS = ("DOMESTIC", "FOREIGN")


@bp.post("/registry/facilities")
@require_roles("FacilityOwner")
def create_facility(caller_id, caller_role):
    body = json_body()
    ufi = body.get("ufi")
    # Tier 9: uniqueness constraints (checked before tier-12 request shape).
    if isinstance(ufi, str) and ufi:
        for f in db.facilities.values():
            if f["ufi"] == ufi:
                raise ApiError("ERR_DUPLICATE_UFI")
    # Tier 12: request shape.
    legal_name = body.get("legal_name")
    facility_kind = body.get("facility_kind")
    country_code = body.get("country_code")
    if not isinstance(legal_name, str) or not legal_name:
        raise ApiError("ERR_INVALID_REQUEST", "legal_name is required")
    if facility_kind not in FACILITY_KINDS:
        raise ApiError("ERR_INVALID_REQUEST", "facility_kind must be DOMESTIC or FOREIGN")
    if not isinstance(country_code, str) or not country_code:
        raise ApiError("ERR_INVALID_REQUEST", "country_code is required")
    if not isinstance(ufi, str) or not ufi:
        raise ApiError("ERR_INVALID_REQUEST", "ufi is required")

    now = db.now()
    f = db.new_common()
    f.update(
        {
            "legal_name": legal_name,
            "facility_kind": facility_kind,
            "country_code": country_code,
            "ufi": ufi,
            "registration_number": db.next_registration_number(),
            "registration_status": "REGISTERED",
            "registered_at": now,
            "expires_at": now + timedelta(days=services.REGISTRATION_PERIOD_DAYS),
            "violation_count": 0,
            "open_detention_count": 0,
        }
    )
    db.facilities[f["id"]] = f
    return ok(serialize.facility(f), 201)


@bp.get("/registry/facilities/<fid>")
@require_roles(*ALL_ROLES)
def get_facility(fid, caller_id, caller_role):
    f = db.facilities.get(fid)
    if f is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    return ok(serialize.facility(f))


@bp.post("/registry/facilities/<fid>/renew")
@require_roles("FacilityOwner")
def renew_facility(fid, caller_id, caller_role):
    # Tier 3: ownership — the caller's X-User-ID must equal the facility id.
    if caller_id != fid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    # Tier 4: existence.
    f = db.facilities.get(fid)
    if f is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    # Tier 5: state — SUSPENDED is absorbing and never renewable.
    if f["registration_status"] not in ("REGISTERED", "EXPIRED"):
        raise ApiError("ERR_FACILITY_NOT_RENEWABLE")
    # Tier 7: renewal window [expires_at - 90d, expires_at + 30d], inclusive.
    now = db.now()
    expires_at = f["expires_at"]
    window_open = expires_at - timedelta(days=services.RENEWAL_OPEN_DAYS_BEFORE)
    window_close = expires_at + timedelta(days=services.RENEWAL_GRACE_DAYS_AFTER)
    if not (window_open <= now <= window_close):
        raise ApiError("ERR_RENEWAL_WINDOW_CLOSED")
    body = json_body()
    expected = body.get("expected_facility_version", services.MISSING)
    # Tier 10: optimistic concurrency on the facility version.
    if (
        expected is not services.MISSING
        and services.is_int(expected)
        and expected != f["version"]
    ):
        raise ApiError("ERR_STALE_VERSION")
    # Tier 12: the OCC field is required and must be an integer.
    if expected is services.MISSING or not services.is_int(expected):
        raise ApiError("ERR_INVALID_REQUEST", "expected_facility_version is required")

    if f["registration_status"] == "REGISTERED":
        # Renewal before expiry extends from the old expiry.
        f["expires_at"] = expires_at + timedelta(days=services.REGISTRATION_PERIOD_DAYS)
    else:
        # Renewal from EXPIRED resets from the current logical instant.
        f["registration_status"] = "REGISTERED"
        f["expires_at"] = now + timedelta(days=services.REGISTRATION_PERIOD_DAYS)
    db.touch(f, now)
    return ok(serialize.facility(f))
