"""Certification routes."""
from flask import Blueprint

from db import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_CONTRACTOR_SUSPENDED,
    ERR_INSURANCE_EXPIRED, ERR_LICENSE_EXPIRED, ERR_INSUFFICIENT_TRAINING_CREDITS,
    ERR_STALE_CERTIFICATION_VERSION, ERR_OWNERSHIP_MISMATCH, not_found,
)
from middleware import require_roles
from response import success, list_response
from services.helpers import (
    body_json, require_fields, require_string, require_enum, stamp_common, touch,
    clock_date, add_months,
)
from services.calculations import training_credit_total, TIER_MIN_CREDITS
from services.cascades import lazy_expire_certifications

bp = Blueprint("certifications", __name__)

TIERS = ("BRONZE", "SILVER", "GOLD")


def _get_cert(cid):
    lazy_expire_certifications(db)
    cert = db.certifications.get(cid)
    if cert is None:
        raise not_found("Certification")
    return cert


def _get_contractor(cid):
    c = db.contractors.get(cid)
    if c is None:
        raise not_found("Contractor")
    return c


@bp.post("/program/certifications")
def create_certification():
    user_id, role = require_roles("Contractor", "ProgramAdmin")
    data = body_json()
    require_fields(data, ["contractor_id", "tier"])
    contractor_id = require_string(data, "contractor_id")
    tier = require_enum(data, "tier", TIERS)
    with db.lock:
        if role == "Contractor" and contractor_id != user_id:
            raise ApiError(ERR_OWNERSHIP_MISMATCH, 403, "Contractor may only apply for self")
        contractor = _get_contractor(contractor_id)
        if contractor["status"] != "ACTIVE":
            raise ApiError(ERR_CONTRACTOR_SUSPENDED, 409, "Contractor is not ACTIVE")
        cert = stamp_common({
            "contractor_id": contractor_id,
            "tier": tier,
            "status": "PENDING_VERIFICATION",
            "valid_from": None,
            "valid_until": None,
        })
        db.certifications[cert["id"]] = cert
    return success(cert, status=201)


@bp.get("/program/certifications/<cid>")
def get_certification(cid):
    require_roles("ProgramAdmin", "Contractor")
    with db.lock:
        cert = _get_cert(cid)
    return success(cert)


def _check_standing(contractor, cert, today, check_license=True, check_training=True):
    """Verify/renew shared gates: contractor ACTIVE, insurance, license, training."""
    if contractor["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACTOR_SUSPENDED, 409, "Contractor is not ACTIVE")
    if clock_date_from(contractor["insurance_expiry"]) <= today:
        raise ApiError(ERR_INSURANCE_EXPIRED, 422, "Contractor insurance expired")
    if check_license:
        if clock_date_from(contractor["license_expiry"]) <= today:
            raise ApiError(ERR_LICENSE_EXPIRED, 422, "Contractor license expired")
    if check_training:
        total = training_credit_total(db, contractor["id"], today)
        if total < TIER_MIN_CREDITS[cert["tier"]]:
            raise ApiError(ERR_INSUFFICIENT_TRAINING_CREDITS, 422,
                           "Insufficient training credits")


def clock_date_from(s):
    from datetime import date
    return date.fromisoformat(s)


@bp.post("/program/certifications/<cid>/verify")
def verify_certification(cid):
    require_roles("ProgramAdmin")
    data = body_json()
    require_fields(data, ["decision"])
    decision = require_enum(data, "decision", ("APPROVE", "DENY"))
    with db.lock:
        cert = db.certifications.get(cid)
        if cert is None:
            raise not_found("Certification")
        if cert["status"] != "PENDING_VERIFICATION":
            raise ApiError(ERR_INVALID_STATE, 409, "Certification is not PENDING_VERIFICATION")
        contractor = _get_contractor(cert["contractor_id"])
        if decision == "DENY":
            cert["status"] = "DENIED"
            touch(cert)
            return success(cert)
        today = clock_date(db)
        _check_standing(contractor, cert, today)
        cert["status"] = "ACTIVE"
        cert["valid_from"] = today.isoformat()
        cert["valid_until"] = add_months(today, 24).isoformat()
        touch(cert)
    return success(cert)


@bp.post("/program/certifications/<cid>/reinstate")
def reinstate_certification(cid):
    require_roles("ProgramAdmin")
    with db.lock:
        cert = _get_cert(cid)
        if cert["status"] != "SUSPENDED":
            raise ApiError(ERR_INVALID_STATE, 409, "Certification is not SUSPENDED")
        contractor = _get_contractor(cert["contractor_id"])
        today = clock_date(db)
        if contractor["status"] != "ACTIVE":
            raise ApiError(ERR_CONTRACTOR_SUSPENDED, 409, "Contractor is not ACTIVE")
        if clock_date_from(contractor["insurance_expiry"]) <= today:
            raise ApiError(ERR_INSURANCE_EXPIRED, 422, "Contractor insurance expired")
        cert["status"] = "ACTIVE"
        touch(cert)
    return success(cert)


@bp.post("/program/certifications/<cid>/renew")
def renew_certification(cid):
    user_id, role = require_roles("Contractor")
    data = body_json()
    require_fields(data, ["expected_certification_version"])
    ecv = data["expected_certification_version"]
    if not isinstance(ecv, int) or isinstance(ecv, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_certification_version must be an integer")
    with db.lock:
        cert = _get_cert(cid)
        if cert["contractor_id"] != user_id:
            raise ApiError(ERR_OWNERSHIP_MISMATCH, 403, "Contractor may only renew own certification")
        if cert["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409, "Certification is not ACTIVE")
        contractor = _get_contractor(cert["contractor_id"])
        today = clock_date(db)
        if contractor["status"] != "ACTIVE":
            raise ApiError(ERR_CONTRACTOR_SUSPENDED, 409, "Contractor is not ACTIVE")
        if ecv != cert["version"]:
            raise ApiError(ERR_STALE_CERTIFICATION_VERSION, 412,
                           "Stale certification version")
        if clock_date_from(contractor["insurance_expiry"]) <= today:
            raise ApiError(ERR_INSURANCE_EXPIRED, 422, "Contractor insurance expired")
        if clock_date_from(contractor["license_expiry"]) <= today:
            raise ApiError(ERR_LICENSE_EXPIRED, 422, "Contractor license expired")
        total = training_credit_total(db, contractor["id"], today)
        if total < TIER_MIN_CREDITS[cert["tier"]]:
            raise ApiError(ERR_INSUFFICIENT_TRAINING_CREDITS, 422,
                           "Insufficient training credits")
        from datetime import date
        prior = date.fromisoformat(cert["valid_until"])
        cert["valid_until"] = add_months(prior, 24).isoformat()
        touch(cert)
    return success(cert)


@bp.get("/program/certifications/<cid>/warranty-registrations")
def list_cert_registrations(cid):
    require_roles("ProgramAdmin", "Contractor")
    with db.lock:
        cert = _get_cert(cid)
        rows = sorted(
            (r for r in db.registrations.values() if r["certification_id"] == cert["id"]),
            key=lambda x: x["created_at"],
        )
    return list_response(rows, len(rows), len(rows), 0)
