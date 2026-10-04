"""ClientAuditEvent endpoints: schedule, complete, cancel."""

from flask import Blueprint

from db import db
from errors import err_not_found, err_invalid_state, err_forbidden_ownership
from middleware import require_role, ALL_ROLES
from response import success_object
from services.cascades import suspend_client_cascade
from services.common import body_json, require_fields, check_enum, touch

bp = Blueprint("audit_events", __name__)

OUTCOMES = {"CLEAN", "REIDENTIFICATION_ATTEMPTED"}


def _get_event(aid):
    event = db.audit_events.get(aid)
    if event is None:
        raise err_not_found("Audit event not found")
    return event


@bp.route("/audit-events/<aid>", methods=["GET"])
def get_event(aid):
    require_role(ALL_ROLES)
    return success_object(_get_event(aid))


@bp.route("/audit-events/<aid>/schedule", methods=["POST"])
def schedule_event(aid):
    require_role(["PlatformAdmin"])
    event = _get_event(aid)
    if event["status"] != "REQUESTED":
        raise err_invalid_state("Audit event must be REQUESTED to schedule")
    event["status"] = "SCHEDULED"
    touch(event)
    return success_object(event)


@bp.route("/audit-events/<aid>/complete", methods=["POST"])
def complete_event(aid):
    require_role(["PlatformAdmin"])
    event = _get_event(aid)
    data = body_json()
    require_fields(data, ["outcome"])
    outcome = check_enum(data, "outcome", OUTCOMES)
    if event["status"] != "SCHEDULED":
        raise err_invalid_state("Audit event must be SCHEDULED to complete")
    event["outcome"] = outcome
    event["status"] = "COMPLETED"
    touch(event)
    if outcome == "REIDENTIFICATION_ATTEMPTED":
        client = db.clients[event["client_id"]]
        if client["status"] == "ACTIVE":
            suspend_client_cascade(client)
    return success_object(event)


@bp.route("/audit-events/<aid>/cancel", methods=["POST"])
def cancel_event(aid):
    user_id, role = require_role(["PlatformAdmin", "ManufacturerClient"])
    event = _get_event(aid)
    if role == "ManufacturerClient" and user_id != event["client_id"]:
        raise err_forbidden_ownership()
    if event["status"] not in ("REQUESTED", "SCHEDULED"):
        raise err_invalid_state("Audit event must be REQUESTED or SCHEDULED to cancel")
    event["status"] = "CANCELLED"
    touch(event)
    return success_object(event)
