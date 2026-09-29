"""Activity signups, admission, waitlists and releases (PRD 3.8)."""

from flask import Blueprint

import calc
import serialize
from auth import authorize, own_registration, own_signup
from envelope import created, ok, paginate
from errors import fail
from gates import filtered, lookup, program_gate
from schema import body, f_id, f_int, raw_fk, validate
from store import db

bp = Blueprint("activity_signups", __name__)

SIGNUP_ROLES = ("ProgramDirector", "SalesOpsAnalyst", "TravelDesk", "Participant")


@bp.post("/activity-signups")
def create_signup():
    actor = authorize("TravelDesk", "Participant")
    payload = body()

    # 5 - body foreign keys in declared order.
    activity_id = raw_fk(payload, "activity_id")
    if activity_id is not None:
        lookup("activity", activity_id)
    registration_id = raw_fk(payload, "registration_id")
    registration = (lookup("registration", registration_id)
                    if registration_id is not None else None)

    # 6 - participant ownership.
    if registration is not None:
        own_registration(actor, registration)

    # 7 - request schema.
    data = validate(payload, [
        f_id("activity_id"),
        f_id("registration_id"),
        f_int("expected_activity_version"),
    ])
    activity = lookup("activity", data["activity_id"])
    registration = lookup("registration", data["registration_id"])
    own_registration(actor, registration)

    # 9 - stale parent version.
    if data["expected_activity_version"] != activity["version"]:
        fail("ERR_STALE_ACTIVITY_VERSION")

    # 10 - lifecycle.
    program_gate(db.programs.get(activity["program_id"]), ("ONSITE",))

    # 12 - cross-entity state, activity axis before the attendance axis.
    if activity["status"] != "OPEN":
        fail("ERR_ACTIVITY_STATE_INVALID")
    if registration["attendance_status"] not in ("CONFIRMED", "TRAVELLED"):
        fail("ERR_REGISTRATION_STATE_INVALID")

    # 16 - the high-risk waiver.
    if activity["risk_level"] == "HIGH" and not registration["waiver_on_file"]:
        fail("ERR_ACTIVITY_WAIVER_REQUIRED")

    # 22 - at most one live signup per activity-and-registration pair.
    for existing in db.activity_signups.values():
        if (existing["activity_id"] == activity["id"]
                and existing["registration_id"] == registration["id"]
                and existing["status"] != "CANCELLED"):
            fail("ERR_DUPLICATE_ACTIVITY_SIGNUP")

    # 24 - the 45-minute transfer buffer.
    if calc.has_schedule_conflict(db, registration["id"], activity):
        fail("ERR_ACTIVITY_TIME_CONFLICT")

    # 31 - the activity and the seat must sit in the same program.
    if activity["program_id"] != registration["program_id"]:
        fail("ERR_PROGRAM_SCOPE_MISMATCH")

    calc.activity_counts(db, activity)
    admitted = "BOOKED" if activity["booked_count"] < activity["capacity"] else "WAITLISTED"

    row = {
        "activity_id": activity["id"],
        "registration_id": registration["id"],
        "status": admitted,
        "promoted_at": None,
    }
    db.stamp_new(row)
    db.activity_signups[row["id"]] = row

    calc.activity_counts(db, activity)
    db.touch(activity)
    return created(serialize.activity_signup(row))


@bp.get("/activity-signups/<signup_id>")
def read_signup(signup_id):
    actor = authorize(*SIGNUP_ROLES)
    signup = lookup("signup", signup_id)
    own_signup(actor, signup)
    return ok(serialize.activity_signup(signup))


@bp.get("/activity-signups")
def list_signups():
    authorize(*SIGNUP_ROLES)
    rows = filtered(db.ordered(db.activity_signups), [
        ("activity_id", "activity_id"),
        ("registration_id", "registration_id"),
        ("status", "status"),
    ])
    return paginate(rows, serialize.activity_signup)


@bp.post("/activity-signups/<signup_id>/cancel")
def cancel_signup(signup_id):
    actor = authorize("TravelDesk", "Participant")
    signup = lookup("signup", signup_id)
    own_signup(actor, signup)
    body()
    activity = db.onsite_activities.get(signup["activity_id"])
    program_gate(db.programs.get(activity["program_id"]), ("ONSITE",))

    if activity["status"] != "OPEN":
        fail("ERR_ACTIVITY_STATE_INVALID")
    if signup["status"] == "CANCELLED":
        fail("ERR_SIGNUP_STATE_INVALID")

    was_booked = signup["status"] == "BOOKED"
    signup["status"] = "CANCELLED"
    db.touch(signup)

    calc.activity_counts(db, activity)
    if was_booked:
        calc.promote_one(db, activity)
    calc.activity_counts(db, activity)
    db.touch(activity)

    return ok(serialize.activity_signup(signup))
