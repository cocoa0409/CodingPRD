"""Clock and contractor routes."""
from flask import Blueprint

from db import db
from errors import ApiError, ERR_INVALID_REQUEST, not_found
from middleware import require_roles
from response import success, list_response
from services.helpers import (
    body_json, require_fields, require_string, require_string_list,
    parse_date, valid_iso8601, format_clock, parse_clock, stamp_common, touch,
    now_ts,
)
from services.cascades import lazy_expire_certifications, reinstate_suspended_contractors

bp = Blueprint("core", __name__)


@bp.post("/program/_clock/set_current_utc")
def set_clock():
    require_roles("ProgramAdmin")
    data = body_json()
    require_fields(data, ["to_iso8601"])
    to = data["to_iso8601"]
    if not valid_iso8601(to):
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be ISO8601 YYYY-MM-DDTHH:MM:SSZ")
    with db.lock:
        db.clock = to
        lazy_expire_certifications(db)
        reinstate_suspended_contractors(db)
    return success({"current_utc": db.clock})


@bp.post("/program/contractors")
def create_contractor():
    require_roles("ProgramAdmin")
    data = body_json()
    require_fields(data, ["legal_name", "license_number", "license_expiry",
                          "insurance_expiry", "territory_codes"])
    legal_name = require_string(data, "legal_name")
    license_number = require_string(data, "license_number")
    license_expiry = require_string(data, "license_expiry")
    parse_date(license_expiry)
    insurance_expiry = require_string(data, "insurance_expiry")
    parse_date(insurance_expiry)
    territory_codes = require_string_list(data, "territory_codes")
    with db.lock:
        c = stamp_common({
            "legal_name": legal_name,
            "license_number": license_number,
            "license_expiry": license_expiry,
            "insurance_expiry": insurance_expiry,
            "territory_codes": list(territory_codes),
            "status": "ACTIVE",
            "workmanship_score": 100,
            "complaint_score_24mo": 0,
            "lifetime_substantiated_count": 0,
            "outstanding_liability_cents": 0,
        })
        db.contractors[c["id"]] = c
    return success(c, status=201)


def _get_contractor(cid):
    c = db.contractors.get(cid)
    if c is None:
        raise not_found("Contractor")
    return c


@bp.get("/program/contractors/<cid>")
def get_contractor(cid):
    require_roles("ProgramAdmin", "Contractor", "Distributor")
    with db.lock:
        c = _get_contractor(cid)
    return success(c)


@bp.patch("/program/contractors/<cid>/compliance")
def update_compliance(cid):
    require_roles("ProgramAdmin")
    data = body_json()
    with db.lock:
        c = _get_contractor(cid)
        if "license_number" in data:
            if not isinstance(data["license_number"], str) or data["license_number"] == "":
                raise ApiError(ERR_INVALID_REQUEST, 400, "license_number must be a non-empty string")
            c["license_number"] = data["license_number"]
        if "license_expiry" in data:
            parse_date(data["license_expiry"])
            c["license_expiry"] = data["license_expiry"]
        if "insurance_expiry" in data:
            parse_date(data["insurance_expiry"])
            c["insurance_expiry"] = data["insurance_expiry"]
        touch(c)
    return success(c)


@bp.get("/program/contractors/<cid>/certifications")
def list_contractor_certifications(cid):
    require_roles("ProgramAdmin", "Contractor")
    with db.lock:
        c = _get_contractor(cid)
        from services.cascades import lazy_expire_certifications
        lazy_expire_certifications(db)
        certs = sorted(
            (x for x in db.certifications.values() if x["contractor_id"] == c["id"]),
            key=lambda x: x["created_at"],
        )
    return list_response(certs, len(certs), len(certs), 0)


@bp.get("/program/contractors/<cid>/complaints")
def list_contractor_complaints(cid):
    require_roles("ProgramAdmin")
    with db.lock:
        c = _get_contractor(cid)
        rows = sorted(
            (x for x in db.complaints.values() if x["contractor_id"] == c["id"]),
            key=lambda x: x["created_at"],
        )
    return list_response(rows, len(rows), len(rows), 0)
