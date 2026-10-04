from flask import Blueprint, request

from db import db, new_id, format_iso
from middleware import get_user_context, require_roles, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, touch, require_fields, resolve, list_paginated,
    parse_datetime_value, ASSIGNMENT_NON_TERMINAL,
)
from errors import ApiError

bp = Blueprint("shift_assignments", __name__)


def serialize(a):
    return {
        "id": a["id"],
        "cook_id": a["cook_id"],
        "station_id": a["station_id"],
        "shift_start": a["shift_start"],
        "shift_end": a["shift_end"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def shift_minutes(a):
    start = parse_datetime_value(a["shift_start"], "shift_start")
    end = parse_datetime_value(a["shift_end"], "shift_end")
    return int((end - start).total_seconds() // 60)


@bp.route("/api/shift-assignments", methods=["POST"])
def create_assignment():
    get_user_context()
    body = get_json_body()
    require_fields(body, ["cook_id", "station_id", "shift_start", "shift_end"])
    cid = body["cook_id"]
    sid = body["station_id"]
    start = parse_datetime_value(body.get("shift_start"), "shift_start")
    end = parse_datetime_value(body.get("shift_end"), "shift_end")
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", 400, "shift_end must be strictly after shift_start")
    require_roles("KitchenManager")
    cook = resolve("cook", cid)
    station = resolve("station", sid)
    if station["station_type"] not in cook["certified_station_types"]:
        raise ApiError("ERR_COOK_NOT_CERTIFIED", 422, "Cook is not certified for this station type")
    for other in db.shift_assignments.values():
        if other["cook_id"] != cid or other["status"] not in ASSIGNMENT_NON_TERMINAL:
            continue
        o_start = parse_datetime_value(other["shift_start"], "shift_start")
        o_end = parse_datetime_value(other["shift_end"], "shift_end")
        if start < o_end and o_start < end:
            raise ApiError("ERR_SHIFT_OVERLAP", 409, "Shift overlaps an existing non-terminal assignment")
    ent = {
        "id": new_id(),
        "cook_id": cid,
        "station_id": sid,
        "shift_start": format_iso(start),
        "shift_end": format_iso(end),
        "status": "SCHEDULED",
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.shift_assignments[ent["id"]] = ent
    return success_object(serialize(ent), status=201)


@bp.route("/api/shift-assignments", methods=["GET"])
def list_assignments():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.shift_assignments,
        [("cook_id", "cook_id"), ("station_id", "station_id"), ("status", "status")],
        request.args,
    )
    return success_array([serialize(a) for a in page], limit, offset, total)


@bp.route("/api/shift-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    require_roles(*ALL_ROLES)
    a = resolve("shift_assignment", aid)
    return success_object(serialize(a))


@bp.route("/api/shift-assignments/<aid>/confirm", methods=["POST"])
def confirm(aid):
    get_user_context()
    get_json_body()
    require_roles("KitchenManager")
    a = resolve("shift_assignment", aid)
    if a["status"] != "SCHEDULED":
        raise ApiError("ERR_ASSIGNMENT_NOT_SCHEDULED", 409, "confirm requires SCHEDULED assignment")
    cook = resolve("cook", a["cook_id"])
    if cook["status"] != "ACTIVE":
        raise ApiError("ERR_COOK_NOT_ACTIVE", 409, "Cook must be ACTIVE to confirm")
    a["status"] = "CONFIRMED"
    touch(a)
    cook["weekly_scheduled_minutes"] += shift_minutes(a)
    touch(cook)
    return success_object(serialize(a))


@bp.route("/api/shift-assignments/<aid>/complete", methods=["POST"])
def complete(aid):
    get_user_context()
    get_json_body()
    require_roles("KitchenManager")
    a = resolve("shift_assignment", aid)
    if a["status"] != "CONFIRMED":
        raise ApiError("ERR_ASSIGNMENT_NOT_CONFIRMED", 409, "complete requires CONFIRMED assignment")
    a["status"] = "COMPLETED"
    touch(a)
    return success_object(serialize(a))


@bp.route("/api/shift-assignments/<aid>/cancel", methods=["POST"])
def cancel(aid):
    get_user_context()
    get_json_body()
    require_roles("KitchenManager")
    a = resolve("shift_assignment", aid)
    if a["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_TRANSITION", 409, "cancel requires SCHEDULED or CONFIRMED assignment")
    was_confirmed = a["status"] == "CONFIRMED"
    a["status"] = "CANCELLED"
    touch(a)
    if was_confirmed:
        cook = resolve("cook", a["cook_id"])
        cook["weekly_scheduled_minutes"] -= shift_minutes(a)
        touch(cook)
    return success_object(serialize(a))


@bp.route("/api/shift-assignments/<aid>/mark-no-show", methods=["POST"])
def mark_no_show(aid):
    get_user_context()
    get_json_body()
    require_roles("KitchenManager")
    a = resolve("shift_assignment", aid)
    if a["status"] != "CONFIRMED":
        raise ApiError("ERR_ASSIGNMENT_NOT_CONFIRMED", 409, "mark-no-show requires CONFIRMED assignment")
    a["status"] = "NO_SHOW"
    touch(a)
    cook = resolve("cook", a["cook_id"])
    cook["weekly_scheduled_minutes"] -= shift_minutes(a)
    touch(cook)
    return success_object(serialize(a))
