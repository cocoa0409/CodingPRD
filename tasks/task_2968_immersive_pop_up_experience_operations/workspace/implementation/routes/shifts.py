"""StaffShift — closed occupation intervals with a rest buffer (PRD §3.4)."""

from flask import Blueprint, request

from db import db, new_row, now, public, touch
from errors import ApiError
from middleware import EP, SO, roles
from response import list_response, object_response
from services import derive
from services.validate import Body

bp = Blueprint("shifts", __name__)

STATIONS = ("FLOOR", "BOOTH", "RIGGING", "ENTRY")
SHIFT_DECISIONS = ("COMPLETE", "CANCEL")


@bp.post("/staff-shifts")
@roles(EP)
def schedule_shift():
    body = Body(require_body=True)
    member_id = body.reference("staff_member_id")
    room_id = body.reference("themed_room_id", required=False, default=None)
    start, start_raw = body.instant_field("shift_start_utc")
    end, end_raw = body.instant_field("shift_end_utc")
    station = body.enum("station", STATIONS, required=False, default="FLOOR")

    # rung 5 — body foreign keys; the room is resolved within the run's scope
    member = derive.staff(member_id)
    room_row = None
    if room_id is not None:
        room_row = derive.room(room_id)
        if room_row["run_id"] != member["run_id"]:
            raise ApiError("ERR_ROOM_NOT_FOUND")

    # rung 9 — only a cleared person may be booked
    if member["status"] != "CLEARED":
        raise ApiError("ERR_STAFF_NOT_CLEARED")

    # rung 11 — interval bounds
    if end <= start:
        raise ApiError("ERR_INVALID_WINDOW")

    # rung 13 — the collision sweep first, the length second
    derive.check_shift_geometry(member, start, end)

    row = new_row()
    row.update({
        "staff_member_id": member["id"],
        "run_id": member["run_id"],
        "themed_room_id": room_row["id"] if room_row is not None else None,
        "shift_start_utc": start_raw,
        "shift_end_utc": end_raw,
        "station": station,
        "status": "SCHEDULED",
        "_start": start,
        "_end": end,
    })
    db.shifts[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/staff-shifts/<shift_id>")
@roles(EP, SO)
def read_shift(shift_id):
    return object_response(public(derive.shift(shift_id)))


@bp.get("/staff-shifts")
@roles(EP, SO)
def list_shifts():
    rows = list(db.shifts.values())
    for field in ("staff_member_id", "run_id", "themed_room_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return list_response(rows)


@bp.post("/staff-shifts/<shift_id>/status-decisions")
@roles(EP)
def shift_decision(shift_id):
    shift_row = derive.shift(shift_id)
    body = Body(require_body=True)
    decision = body.enum("decision", SHIFT_DECISIONS)
    body.string("note", required=False, default=None, min_len=1, max_len=500)

    # rung 8 — own state; both targets are terminal
    if shift_row["status"] != "SCHEDULED":
        raise ApiError("ERR_SHIFT_INVALID_STATE")

    if decision == "COMPLETE":
        # rung 12 — the clock must have reached the end instant
        if now() < shift_row["_end"]:
            raise ApiError("ERR_SHIFT_NOT_ENDED")
        shift_row["status"] = "COMPLETED"
    else:
        shift_row["status"] = "CANCELLED"

    touch(shift_row)
    return object_response(public(shift_row))
