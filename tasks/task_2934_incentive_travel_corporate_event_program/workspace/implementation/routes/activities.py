"""The on-site agenda (PRD 3.8)."""

from flask import Blueprint

import cascades
import serialize
from auth import ALL_ROLES, authorize
from envelope import created, ok, paginate
from errors import fail
from gates import filtered, lookup, program_gate
from schema import body, f_dt, f_enum, f_id, f_int, f_str, raw_fk, validate
from store import db, norm_dt, parse_dt

bp = Blueprint("onsite_activities", __name__)

RISKS = ("LOW", "MEDIUM", "HIGH")


@bp.post("/onsite-activities")
def create_activity():
    authorize("TravelDesk")
    payload = body()

    program_id = raw_fk(payload, "program_id")
    if program_id is not None:
        lookup("program", program_id)

    data = validate(payload, [
        f_id("program_id"),
        f_str("name", max_len=160),
        f_dt("start_at"),
        f_dt("end_at"),
        f_int("capacity", minimum=0),
        f_enum("risk_level", RISKS),
    ])
    program = lookup("program", data["program_id"])
    program_gate(program, ("CONTRACTED", "REGISTRATION_OPEN", "ONSITE"))

    if not (parse_dt(data["end_at"]) > parse_dt(data["start_at"])):
        fail("ERR_INVALID_DATE_RANGE")

    row = {
        "program_id": program["id"],
        "name": data["name"],
        "start_at": norm_dt(data["start_at"]),
        "end_at": norm_dt(data["end_at"]),
        "capacity": data["capacity"],
        "risk_level": data["risk_level"],
        "status": "OPEN",
        "booked_count": 0,
        "waitlist_count": 0,
    }
    db.stamp_new(row)
    db.onsite_activities[row["id"]] = row
    return created(serialize.onsite_activity(row))


@bp.get("/onsite-activities/<activity_id>")
def read_activity(activity_id):
    authorize(*ALL_ROLES)
    return ok(serialize.onsite_activity(lookup("activity", activity_id)))


@bp.get("/onsite-activities")
def list_activities():
    authorize(*ALL_ROLES)
    rows = filtered(db.ordered(db.onsite_activities), [
        ("program_id", "program_id"),
        ("status", "status"),
        ("risk_level", "risk_level"),
    ])
    return paginate(rows, serialize.onsite_activity)


@bp.post("/onsite-activities/<activity_id>/close")
def close_activity(activity_id):
    authorize("TravelDesk")
    activity = lookup("activity", activity_id)
    body()
    program_gate(db.programs.get(activity["program_id"]),
                 ("REGISTRATION_OPEN", "ONSITE"))

    if activity["status"] != "OPEN":
        fail("ERR_ACTIVITY_STATE_INVALID")

    cascades.close_activity(activity)
    return ok(serialize.onsite_activity(activity))
