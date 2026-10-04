"""Agreement lifecycle endpoints."""
import datetime

import flask

import db
from helpers import (err, success, get_json_body, require_fields, parse_pagination,
                     list_response, stamp_new, touch)
from middleware import authenticate, require_role, check_ownership, authorize_agreement_path
from services import terminal_sweep

bp = flask.Blueprint("agreements", __name__)
ALL = ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor")


@bp.post("/licensing/agreements")
def create_agreement():
    _, role = authenticate()
    require_role(role, ("ProgramAdministrator",))
    body = get_json_body()
    require_fields(body, ["organization_id", "enrollment_number", "start_date", "end_date"])
    org = db.organizations.get(body["organization_id"])
    if org is None:
        err("ERR_NOT_FOUND", "Organization not found.", 404)
    if not isinstance(body["enrollment_number"], str):
        err("ERR_INVALID_REQUEST", "enrollment_number must be a string.", 400)
    for a in db.agreements.values():
        if a["enrollment_number"] == body["enrollment_number"]:
            err("ERR_DUPLICATE_ENROLLMENT", "enrollment_number already exists.", 409)
    try:
        start = db.parse_date(body["start_date"])
        end = db.parse_date(body["end_date"])
    except Exception:
        err("ERR_INVALID_REQUEST", "start_date and end_date must be ISO dates.", 400)
    if end < start:
        err("ERR_INVALID_DATE_RANGE", "end_date must not be before start_date.", 422)
    ag = {
        "organization_id": org["id"],
        "enrollment_number": body["enrollment_number"],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "status": "DRAFT",
        "renewal_count": 0,
    }
    stamp_new(ag, with_version=True)
    db.agreements[ag["id"]] = ag
    return success(ag, status=201, response_type="object")


@bp.get("/licensing/agreements/<ag_id>")
def get_agreement(ag_id):
    _, role, ag = authorize_agreement_path(ALL, ag_id)
    return success(ag, status=200, response_type="object")


@bp.post("/licensing/agreements/<ag_id>/activate")
def activate(ag_id):
    _, role, ag = authorize_agreement_path(("ProgramAdministrator",), ag_id)
    if ag["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Agreement is not in DRAFT.", 409)
    if db.today() > db.parse_date(ag["start_date"]):
        err("ERR_ACTIVATION_WINDOW_MISSED", "Activation is only possible on or before start_date.", 422)
    ag["status"] = "ACTIVE"
    touch(ag)
    return success(ag, status=200, response_type="object")


@bp.post("/licensing/agreements/<ag_id>/renewal-review")
def renewal_review(ag_id):
    _, role, ag = authorize_agreement_path(("LicensingSpecialist",), ag_id)
    if ag["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Agreement is not ACTIVE.", 409)
    end = db.parse_date(ag["end_date"])
    today = db.today()
    if not (end - datetime.timedelta(days=90) <= today <= end):
        err("ERR_RENEWAL_WINDOW", "Renewal review is only allowed within 90 days before end_date.", 422)
    ag["status"] = "RENEWAL_PENDING"
    touch(ag)
    return success(ag, status=200, response_type="object")


@bp.post("/licensing/agreements/<ag_id>/renew")
def renew(ag_id):
    _, role, ag = authorize_agreement_path(("ProgramAdministrator",), ag_id)
    if ag["status"] != "RENEWAL_PENDING":
        err("ERR_INVALID_STATE", "Agreement is not RENEWAL_PENDING.", 409)
    body = get_json_body()
    require_fields(body, ["new_end_date", "expected_agreement_version"])
    if not isinstance(body["expected_agreement_version"], int) or isinstance(body["expected_agreement_version"], bool):
        err("ERR_INVALID_REQUEST", "expected_agreement_version must be an integer.", 400)
    try:
        new_end = db.parse_date(body["new_end_date"])
    except Exception:
        err("ERR_INVALID_REQUEST", "new_end_date must be an ISO date.", 400)
    if db.today() > db.parse_date(ag["end_date"]):
        err("ERR_INVALID_STATE", "Agreement term has already ended.", 409)
    if new_end <= db.parse_date(ag["end_date"]):
        err("ERR_INVALID_DATE_RANGE", "new_end_date must be after the current end_date.", 422)
    if body["expected_agreement_version"] != ag["version"]:
        err("ERR_STALE_VERSION", "expected_agreement_version does not match the current version.", 412)
    ag["status"] = "RENEWED"
    ag["renewal_count"] += 1
    ag["end_date"] = new_end.isoformat()
    touch(ag)
    for ann in db.anniversaries.values():
        if ann["agreement_id"] == ag["id"] and not ann["true_up_closed"]:
            ann["true_up_closed"] = True
            touch(ann)
    return success(ag, status=200, response_type="object")


@bp.post("/licensing/agreements/<ag_id>/decline-renewal")
def decline_renewal(ag_id):
    _, role, ag = authorize_agreement_path(("CustomerAdmin",), ag_id)
    if ag["status"] != "RENEWAL_PENDING":
        err("ERR_INVALID_STATE", "Agreement is not RENEWAL_PENDING.", 409)
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("CONTINUE", "NON_RENEW"):
        err("ERR_INVALID_REQUEST", "decision must be CONTINUE or NON_RENEW.", 400)
    if decision == "CONTINUE":
        ag["status"] = "ACTIVE"
        touch(ag)
    else:
        ag["status"] = "NON_RENEWED"
        touch(ag)
        terminal_sweep(ag["id"])
    return success(ag, status=200, response_type="object")


@bp.post("/licensing/agreements/<ag_id>/expire")
def expire(ag_id):
    _, role, ag = authorize_agreement_path(("ProgramAdministrator",), ag_id)
    if ag["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Agreement is not ACTIVE.", 409)
    if db.today() <= db.parse_date(ag["end_date"]):
        err("ERR_INVALID_STATE", "Agreement term has not ended yet.", 409)
    ag["status"] = "EXPIRED"
    touch(ag)
    terminal_sweep(ag["id"])
    return success(ag, status=200, response_type="object")
