"""Appeals to the city council (PRD 3.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_FORBIDDEN_ROLE, ERR_INVALID_STATE,
    ERR_APPEAL_WINDOW_LAPSED, ERR_APPEAL_ALREADY_PENDING, ERR_VALIDATION,
)
from middleware import get_caller, check_role_allowed
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import new_record, touch
from services.workflows import after_the_fact_resolution
from util import CLOCK, parse_dt, fmt_dt, add_days
from validate import get_body, req_str, req_enum, require_path_resource, require_body_ref

bp = Blueprint("appeals", __name__, url_prefix="/preservation")

APPEAL_WINDOW_DAYS = 30
APPEAL_OUTCOMES = {"SUSTAIN", "UPHOLD"}


@bp.post("/appeals")
def create_appeal():
    caller = get_caller()
    body = get_body()
    application_id = req_str(body, "application_id")
    grounds = req_str(body, "grounds")
    check_role_allowed(caller, ["Applicant"])
    app = require_body_ref("applications", application_id, "application_id")
    # Layer 2: only the owning applicant may appeal.
    if caller.user_id != app["owner_id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "only the owning applicant may appeal")
    # Layer 5: only a DENIED application can be appealed.
    if app["status"] != "DENIED":
        raise_error(ERR_INVALID_STATE,
                    f"appeals require a DENIED application, got {app['status']}")
    # Layer 8: the filing window is decided_at + 30 days, boundary inclusive.
    if CLOCK.now() > add_days(parse_dt(app["decided_at"]), APPEAL_WINDOW_DAYS):
        raise_error(ERR_APPEAL_WINDOW_LAPSED,
                    "the appeal window (decided_at + 30 days) has lapsed")
    # Layer 9: one pending appeal per application.
    for other in db["appeals"].values():
        if other.get("application_id") == app["id"] and other.get("status") == "FILED":
            raise_error(ERR_APPEAL_ALREADY_PENDING,
                        "an appeal for this application is already FILED")
    rec = new_record("appeals", {
        "application_id": app["id"],
        "filed_at": CLOCK.now_iso(),
        "grounds": grounds,
        "council_findings": None,
        "decided_at": None,
        "status": "FILED",
    })
    return success_object(public(rec), status=201)


@bp.get("/appeals")
def list_appeals():
    filters = {
        "application_id": request.args.get("application_id"),
        "status": request.args.get("status"),
    }
    return list_response("appeals", filters)


@bp.get("/appeals/<rid>")
def get_appeal(rid):
    return get_one("appeals", rid)


@bp.post("/appeals/<rid>/decide")
def decide_appeal(rid):
    caller = get_caller()
    body = get_body()
    outcome = req_enum(body, "outcome", APPEAL_OUTCOMES)
    council_findings = req_str(body, "council_findings")
    check_role_allowed(caller, ["CouncilMember"])
    appeal = require_path_resource("appeals", rid)
    if appeal["status"] != "FILED":
        raise_error(ERR_INVALID_STATE,
                    f"appeal decide requires FILED, got {appeal['status']}")

    decided_dt = CLOCK.now()
    appeal["decided_at"] = fmt_dt(decided_dt)
    appeal["council_findings"] = council_findings
    app = db["applications"].get(appeal["application_id"])
    if outcome == "SUSTAIN":
        appeal["status"] = "DECIDED_SUSTAINED"
        if app is not None and app["status"] == "DENIED":
            app["status"] = "APPROVED_ON_APPEAL"
            touch(app)
            # After-the-fact cascade: accrual stops at the appeal's decided_at.
            if app.get("after_the_fact"):
                after_the_fact_resolution(app, decided_dt)
    else:  # UPHOLD
        appeal["status"] = "DECIDED_UPHELD"
        if app is not None and app["status"] == "DENIED":
            app["status"] = "DENIED_FINAL"
            touch(app)
    touch(appeal)
    return success_object(public(appeal))


@bp.post("/appeals/<rid>/withdraw")
def withdraw_appeal(rid):
    caller = get_caller()
    get_body()
    check_role_allowed(caller, ["Applicant"])
    appeal = require_path_resource("appeals", rid)
    app = db["applications"].get(appeal["application_id"])
    # Ownership: the caller must own the appeal's application.
    if app is not None and caller.user_id != app["owner_id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "only the owning appellant may withdraw the appeal")
    if appeal["status"] != "FILED":
        raise_error(ERR_INVALID_STATE,
                    f"appeal withdraw requires FILED, got {appeal['status']}")
    appeal["status"] = "WITHDRAWN"
    touch(appeal)
    return success_object(public(appeal))
