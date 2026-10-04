"""Enrollment anniversary endpoints."""
import flask

import db
from helpers import (err, success, get_json_body, require_fields, require_int,
                     parse_pagination, list_response, stamp_new)
from middleware import authenticate, require_role, check_ownership, authorize_agreement_path
from services import sweep_expired_grants

bp = flask.Blueprint("anniversaries", __name__)
ALL = ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor")


@bp.post("/licensing/agreements/<ag_id>/anniversaries")
def create_anniversary(ag_id):
    _, role, ag = authorize_agreement_path(("ProgramAdministrator",), ag_id)
    if ag["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE.", 409)
    body = get_json_body()
    require_fields(body, ["year_index", "period_start", "period_end"])
    year_index = require_int(body, "year_index")
    try:
        period_start = db.parse_date(body["period_start"])
        period_end = db.parse_date(body["period_end"])
    except Exception:
        err("ERR_INVALID_REQUEST", "period_start and period_end must be ISO dates.", 400)
    existing = [a for a in db.anniversaries.values() if a["agreement_id"] == ag["id"]]
    if not (1 <= year_index <= 3):
        err("ERR_INVALID_ANNIVERSARY_SEQUENCE", "year_index must be within 1..3.", 422)
    for a in existing:
        if year_index <= a["year_index"]:
            err("ERR_INVALID_ANNIVERSARY_SEQUENCE",
                "year_index must be strictly greater than all existing year_index values.", 422)
    if period_start < db.parse_date(ag["start_date"]):
        err("ERR_INVALID_ANNIVERSARY_SEQUENCE", "period_start must be >= agreement.start_date.", 422)
    if existing:
        prev = max(existing, key=lambda a: a["year_index"])
        if period_start <= db.parse_date(prev["period_start"]):
            err("ERR_INVALID_ANNIVERSARY_SEQUENCE",
                "period_start must be strictly after the previous anniversary period_start.", 422)
    if period_end <= period_start:
        err("ERR_INVALID_ANNIVERSARY_SEQUENCE", "period_end must be after period_start.", 422)
    ann = {
        "agreement_id": ag["id"],
        "year_index": year_index,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "true_up_closed": False,
    }
    stamp_new(ann, with_version=True)
    db.anniversaries[ann["id"]] = ann
    sweep_expired_grants(ag["id"])
    return success(ann, status=201, response_type="object")


@bp.get("/licensing/agreements/<ag_id>/anniversaries")
def list_anniversaries(ag_id):
    _, role, ag = authorize_agreement_path(ALL, ag_id)
    limit, offset = parse_pagination()
    items = [a for a in db.anniversaries.values() if a["agreement_id"] == ag["id"]]
    return list_response(items, limit, offset)


@bp.get("/licensing/anniversaries/<ann_id>")
def get_anniversary(ann_id):
    user_id, role = authenticate()
    require_role(role, ALL)
    ann = db.anniversaries.get(ann_id)
    if ann is None:
        err("ERR_NOT_FOUND", "Anniversary not found.", 404)
    ag = db.agreements.get(ann["agreement_id"])
    check_ownership(user_id, role, ag["organization_id"] if ag else None)
    return success(ann, status=200, response_type="object")
