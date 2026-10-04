"""Career events and their sessions (window checks, OCC, room conflicts)."""

from flask import Blueprint, request

import db
from db import now, wall_now
from errors import fail
from services import cancel_event_cascade, event_view, room_conflict, session_view
from util import Body, get_context, paginate, require_role, success_object

bp = Blueprint("events", __name__)

EVENT_STATUSES = ("DRAFT", "OPEN", "LOCKED", "COMPLETED", "CANCELLED")
EVENT_TRANSITIONS = {
    ("DRAFT", "OPEN"),
    ("OPEN", "LOCKED"),
    ("LOCKED", "COMPLETED"),
    ("DRAFT", "CANCELLED"),
    ("OPEN", "CANCELLED"),
}
SESSION_MODES = ("VIRTUAL", "IN_PERSON")


def _owned_event(user_id, event_id):
    event = db.get("career_events", event_id)
    if event is None:
        fail("ERR_CAREER_EVENT_NOT_FOUND", "CareerEvent id does not exist")
    if user_id != event["university_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may act only on its own events")
    return event


@bp.route("/career-events", methods=["POST"])
def create_event():
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin")
    body = Body()
    university_id = body.str_f("university_id", required=True)
    title = body.str_f("title", required=True)
    starts_at = body.dt_f("starts_at", required=True)
    ends_at = body.dt_f("ends_at", required=True)
    # Priority 3 ownership, 4 existence, 5 state, 8 temporal, 11 residual.
    if university_id is not None and university_id != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may create events only for its own university")
    university = db.get("universities", university_id) if university_id else None
    if university_id is not None and university is None:
        fail("ERR_UNIVERSITY_NOT_FOUND", "University id does not exist")
    if university is not None and university["status"] != "ACTIVE":
        fail("ERR_UNIVERSITY_NOT_ACTIVE", "University is not ACTIVE")
    if starts_at is not None and ends_at is not None and not starts_at < ends_at:
        fail("ERR_TIME_RANGE_INVALID", "starts_at must be strictly before ends_at")
    body.finalize()
    record = {
        "id": db.new_id(),
        "university_id": university_id,
        "title": title,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "DRAFT",
        "last_session_added_at": None,
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
    }
    db.insert("career_events", record)
    return success_object(event_view(record), 201)


@bp.route("/career-events", methods=["GET"])
def list_events():
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin", "Student", "EmployerRecruiter", "PlatformAdmin")
    records = db.all_of("career_events")
    if role == "CareerCenterAdmin":
        records = [e for e in records if e["university_id"] == user_id]
    f_university = request.args.get("university_id")
    f_status = request.args.get("status")
    if f_university is not None:
        records = [e for e in records if e["university_id"] == f_university]
    if f_status is not None:
        records = [e for e in records if e["status"] == f_status]
    return paginate(records, event_view)


@bp.route("/career-events/<event_id>", methods=["GET"])
def get_event(event_id):
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin", "Student", "EmployerRecruiter", "PlatformAdmin")
    event = db.get("career_events", event_id)
    if event is None:
        fail("ERR_CAREER_EVENT_NOT_FOUND", "CareerEvent id does not exist")
    if role == "CareerCenterAdmin" and user_id != event["university_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may read only its own events")
    return success_object(event_view(event))


@bp.route("/career-events/<event_id>/transition", methods=["POST"])
def transition_event(event_id):
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin")
    event = _owned_event(user_id, event_id)
    body = Body()
    to = body.str_f("to", required=True, enum=EVENT_STATUSES)
    # University suspension blocks event transitions of any kind.
    university = db.get("universities", event["university_id"])
    if university is not None and university["status"] != "ACTIVE":
        fail("ERR_UNIVERSITY_NOT_ACTIVE", "University is not ACTIVE")
    if to is not None and (event["status"], to) not in EVENT_TRANSITIONS:
        fail("ERR_INVALID_EVENT_TRANSITION",
             "Event transition %s -> %s is not allowed" % (event["status"], to))
    body.finalize()
    event["status"] = to
    db.touch(event)
    if to == "CANCELLED":
        cancel_event_cascade(event)
    return success_object(event_view(event))


@bp.route("/career-events/<event_id>/sessions", methods=["POST"])
def create_session(event_id):
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin")
    event = _owned_event(user_id, event_id)
    body = Body()
    title = body.str_f("title", required=True)
    mode = body.str_f("mode", required=True, enum=SESSION_MODES)
    room_present = body.has("room_id")
    room_id = body.raw("room_id")
    if room_present and room_id is not None and not isinstance(room_id, str):
        body.bad = True
        room_id = None
    starts_at = body.dt_f("starts_at", required=True)
    ends_at = body.dt_f("ends_at", required=True)
    signup_deadline = body.dt_f("signup_deadline", required=True)
    capacity = body.int_f("capacity", required=True, minv=1)
    expected_version = body.int_f("expected_career_event_version", required=True)
    # Mode/room shape (recorded; raised only at the residual point).
    if mode == "IN_PERSON" and not room_id:
        body.bad = True
    if mode == "VIRTUAL" and room_id is not None:
        body.bad = True
    # Priority 5 state: university ACTIVE, then event open enough.
    university = db.get("universities", event["university_id"])
    if university is not None and university["status"] != "ACTIVE":
        fail("ERR_UNIVERSITY_NOT_ACTIVE", "University is not ACTIVE")
    if event["status"] not in ("DRAFT", "OPEN"):
        fail("ERR_EVENT_NOT_OPEN", "Session creation requires event status DRAFT or OPEN")
    # Priority 6 OCC on the event version.
    if expected_version is not None and expected_version != event["version"]:
        fail("ERR_STALE_CAREER_EVENT_VERSION",
             "expected_career_event_version does not match the current CareerEvent version")
    # Priority 8 temporal: start-before-end, then containment in the window.
    if starts_at is not None and ends_at is not None and not starts_at < ends_at:
        fail("ERR_TIME_RANGE_INVALID", "starts_at must be strictly before ends_at")
    if (
        starts_at is not None and ends_at is not None and signup_deadline is not None
        and not (
            event["starts_at"] <= starts_at
            and ends_at <= event["ends_at"]
            and signup_deadline <= starts_at
        )
    ):
        fail("ERR_SESSION_OUTSIDE_EVENT_WINDOW",
             "Session must lie inside the event window and signup_deadline <= starts_at")
    # Priority 9 constraint: half-open room overlap.
    if (
        mode == "IN_PERSON" and room_id is not None
        and starts_at is not None and ends_at is not None
        and room_conflict(event["id"], room_id, starts_at, ends_at)
    ):
        fail("ERR_SESSION_ROOM_CONFLICT", "Room %s is already booked for an overlapping session" % room_id)
    body.finalize()
    record = {
        "id": db.new_id(),
        "career_event_id": event["id"],
        "title": title,
        "mode": mode,
        "room_id": room_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "signup_deadline": signup_deadline,
        "capacity": capacity,
        "status": "SCHEDULED",
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
    }
    db.insert("event_sessions", record)
    # Accepting a session stamps the parent and bumps its version (this is
    # what invalidates any other client holding the pre-add version).
    event["last_session_added_at"] = now()
    db.touch(event)
    return success_object(session_view(record), 201)


@bp.route("/career-events/<event_id>/sessions", methods=["GET"])
def list_sessions(event_id):
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin", "Student", "EmployerRecruiter", "PlatformAdmin")
    event = db.get("career_events", event_id)
    if event is None:
        fail("ERR_CAREER_EVENT_NOT_FOUND", "CareerEvent id does not exist")
    if role == "CareerCenterAdmin" and user_id != event["university_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may read only its own events")
    records = [s for s in db.all_of("event_sessions") if s["career_event_id"] == event["id"]]
    return paginate(records, session_view)
