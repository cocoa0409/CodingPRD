"""Servicer notification feed: reads and acknowledgement (PRD §3.4)."""
from flask import Blueprint, request

import db
from auth import ROLE_CLEARINGHOUSE_OPS, ROLE_SERVICER, authenticate, require_role
from core import (
    ERR_INVALID_STATE,
    ERR_NOTIFICATION_NOT_FOUND,
    ERR_UNAUTHORIZED,
    list_response,
    ok_object,
    raise_err,
)

bp = Blueprint("notifications", __name__)

ACCESS_ROLES = (ROLE_CLEARINGHOUSE_OPS, ROLE_SERVICER)


def _get_notification(nid):
    n = db.store.notifications.get(nid)
    if n is None:
        raise_err(ERR_NOTIFICATION_NOT_FOUND, "servicer notification not found")
    return n


@bp.route("/servicer-notifications/<nid>", methods=["GET"])
def get_notification(nid):
    caller = authenticate()
    require_role(caller, *ACCESS_ROLES)
    n = _get_notification(nid)
    if caller.role == ROLE_SERVICER and caller.user_id != n["servicer_ref"]:
        raise_err(ERR_UNAUTHORIZED, "a servicer sees only notifications addressed to its code")
    return ok_object(db.serialize(n))


@bp.route("/servicer-notifications", methods=["GET"])
def list_notifications():
    caller = authenticate()
    require_role(caller, *ACCESS_ROLES)
    q = request.args
    items = list(db.store.notifications.values())
    if caller.role == ROLE_SERVICER:
        items = [n for n in items if n["servicer_ref"] == caller.user_id]
    if q.get("servicer_ref") is not None:
        items = [n for n in items if n["servicer_ref"] == q["servicer_ref"]]
    if q.get("student_id") is not None:
        items = [n for n in items if n["student_id"] == q["student_id"]]
    if q.get("enrollment_entry_id") is not None:
        items = [n for n in items if n["enrollment_entry_id"] == q["enrollment_entry_id"]]
    if q.get("status") is not None:
        items = [n for n in items if n["status"] == q["status"]]
    return list_response(db.sorted_created(items), db.serialize)


@bp.route("/servicer-notifications/<nid>/acknowledge", methods=["POST"])
def acknowledge_notification(nid):
    caller = authenticate()
    require_role(caller, ROLE_SERVICER)
    n = _get_notification(nid)
    if caller.user_id != n["servicer_ref"]:
        raise_err(ERR_UNAUTHORIZED, "a servicer acknowledges only notifications addressed to its code")
    if n["status"] != "SENT":
        raise_err(ERR_INVALID_STATE, "only a SENT notification can be acknowledged")
    n["status"] = "ACKNOWLEDGED"
    db.touch(n)
    student = db.store.students.get(n["student_id"])
    if student is not None:
        student["deferment_standing"] = n["notification_type"]
        db.touch(student)
    return ok_object(db.serialize(n))
