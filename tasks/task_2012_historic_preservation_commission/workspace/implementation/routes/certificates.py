"""Certificates of Appropriateness: issuance, conditions, completion (PRD 3.9)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_UNRESOLVED_VIOLATION_EXISTS,
    ERR_CERTIFICATE_EXISTS, ERR_FEE_BALANCE_OUTSTANDING, ERR_CONDITIONS_UNMET,
    ERR_CERTIFICATE_EXPIRED, ERR_CERTIFICATE_NOT_YET_EXPIRED,
)
from middleware import get_caller, check_role_allowed
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import new_record, touch
from services.workflows import demolition_completion_cascade
from util import CLOCK, parse_dt, fmt_dt, add_days
from validate import (
    get_body, req_str, req_int, req_datetime, require_path_resource,
    require_body_ref,
)

bp = Blueprint("certificates", __name__, url_prefix="/preservation")

STAFF = ["PreservationStaff"]
APPROVAL_TERMINAL = {"APPROVED", "APPROVED_WITH_CONDITIONS", "APPROVED_ON_APPEAL"}
WORK_COMMENCE_DAYS = 365


@bp.post("/certificates")
def create_certificate():
    caller = get_caller()
    body = get_body()
    application_id = req_str(body, "application_id")
    check_role_allowed(caller, STAFF)
    app = require_body_ref("applications", application_id, "application_id")
    # Layer 5: the application must have reached an approval terminal state.
    if app["status"] not in APPROVAL_TERMINAL:
        raise_error(ERR_INVALID_STATE,
                    f"certificate issuance requires an approved application, got {app['status']}")
    prop = db["properties"].get(app["property_id"])
    # Layer 7 (referential) before layer 10 (fiscal): the property must be clean
    # of enforcement before the fee balance is examined.
    if prop is not None and prop.get("open_violation_count", 0) > 0:
        raise_error(ERR_UNRESOLVED_VIOLATION_EXISTS,
                    "the property has unresolved violations")
    # Layer 9 (structural): one certificate per application.
    for existing in db["certificates"].values():
        if existing.get("application_id") == app["id"]:
            raise_error(ERR_CERTIFICATE_EXISTS,
                        "a certificate already exists for this application")
    # Layer 10 (fiscal): the fee account must be settled.
    if app["fee_balance_cents"] > 0:
        raise_error(ERR_FEE_BALANCE_OUTSTANDING,
                    f"fee balance outstanding: {app['fee_balance_cents']}")

    issued_dt = CLOCK.now()
    rec = new_record("certificates", {
        "application_id": app["id"],
        "issued_at": fmt_dt(issued_dt),
        "work_commence_deadline": fmt_dt(add_days(issued_dt, WORK_COMMENCE_DAYS)),
        "conditions": list(app.get("decision_conditions") or []),
        "conditions_met_count": 0,
        "completed_at": None,
        "status": "ISSUED",
    })
    return success_object(public(rec), status=201)


@bp.get("/certificates")
def list_certificates():
    filters = {
        "application_id": request.args.get("application_id"),
        "status": request.args.get("status"),
    }
    return list_response("certificates", filters)


@bp.get("/certificates/<rid>")
def get_certificate(rid):
    return get_one("certificates", rid)


@bp.post("/certificates/<rid>/verify-conditions")
def verify_conditions(rid):
    caller = get_caller()
    body = get_body()
    conditions_met_count = req_int(body, "conditions_met_count", minimum=0)
    check_role_allowed(caller, STAFF)
    cert = require_path_resource("certificates", rid)
    if cert["status"] != "ISSUED":
        raise_error(ERR_INVALID_STATE,
                    f"verify-conditions requires ISSUED, got {cert['status']}")
    if conditions_met_count != len(cert["conditions"]):
        raise_error(ERR_CONDITIONS_UNMET,
                    f"reported {conditions_met_count} of {len(cert['conditions'])} conditions met")
    cert["conditions_met_count"] = conditions_met_count
    cert["status"] = "CONDITIONS_VERIFIED"
    touch(cert)
    return success_object(public(cert))


@bp.post("/certificates/<rid>/complete")
def complete_certificate(rid):
    caller = get_caller()
    body = get_body()
    commenced_at = req_datetime(body, "commenced_at")
    check_role_allowed(caller, STAFF)
    cert = require_path_resource("certificates", rid)
    if cert["status"] != "CONDITIONS_VERIFIED":
        raise_error(ERR_INVALID_STATE,
                    f"complete requires CONDITIONS_VERIFIED, got {cert['status']}")
    # Layer 8 (temporal): work must have commenced AND be completing inside the
    # deadline — both the clock and the payload commenced_at must be at or before it.
    deadline = parse_dt(cert["work_commence_deadline"])
    if CLOCK.now() > deadline or commenced_at > deadline:
        raise_error(ERR_CERTIFICATE_EXPIRED,
                    "the work_commence_deadline has passed")
    cert["completed_at"] = CLOCK.now_iso()
    cert["status"] = "COMPLETED"
    touch(cert)
    demolition_completion_cascade(cert)
    return success_object(public(cert))


@bp.post("/certificates/<rid>/expire")
def expire_certificate(rid):
    caller = get_caller()
    get_body()
    check_role_allowed(caller, STAFF)
    cert = require_path_resource("certificates", rid)
    if cert["status"] not in ("ISSUED", "CONDITIONS_VERIFIED"):
        raise_error(ERR_INVALID_STATE,
                    f"expire requires ISSUED or CONDITIONS_VERIFIED, got {cert['status']}")
    # Expiry is permitted only once the clock has passed the deadline (strict >).
    if CLOCK.now() <= parse_dt(cert["work_commence_deadline"]):
        raise_error(ERR_CERTIFICATE_NOT_YET_EXPIRED,
                    "the work_commence_deadline has not yet passed")
    cert["status"] = "EXPIRED"
    touch(cert)
    return success_object(public(cert))
