"""Event sign-ups: creation with waitlist admission, cancellation, attendance."""

from flask import Blueprint, request

import db
from db import now, wall_now
from errors import fail
from services import promote_waitlist, session_view, signup_view
from util import Body, get_context, paginate, require_role, success_object

bp = Blueprint("signups", __name__)

SIGNUP_STATUSES = ("REGISTERED", "WAITLISTED", "CANCELLED", "ATTENDED", "NO_SHOW")


def _signup_event(signup):
    session = db.get("event_sessions", signup["event_session_id"])
    if session is None:
        return None
    return db.get("career_events", session["career_event_id"])


@bp.route("/event-signups", methods=["POST"])
def create_signup():
    user_id, role = get_context()
    require_role(role, "Student")
    body = Body()
    event_session_id = body.str_f("event_session_id", required=True)
    student_id = body.str_f("student_id", required=True)
    # Priority 3 ownership: the student signs up as themselves.
    if student_id is not None and student_id != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Student may sign up only as themselves")
    # Priority 4 existence, body FK order: event_session_id, then student_id.
    session = db.get("event_sessions", event_session_id) if event_session_id else None
    if event_session_id is not None and session is None:
        fail("ERR_EVENT_SESSION_NOT_FOUND", "EventSession id does not exist")
    student = db.get("students", student_id) if student_id else None
    if student_id is not None and student is None:
        fail("ERR_STUDENT_NOT_FOUND", "Student id does not exist")
    # Priority 5 state gates: ENROLLED, university ACTIVE, event/session signable.
    if student is not None and student["status"] != "ENROLLED":
        fail("ERR_STUDENT_NOT_ENROLLED", "Student must be ENROLLED")
    if student is not None:
        university = db.get("universities", student["university_id"])
        if university is not None and university["status"] != "ACTIVE":
            fail("ERR_UNIVERSITY_NOT_ACTIVE", "University is not ACTIVE")
    event = None
    if session is not None:
        event = db.get("career_events", session["career_event_id"])
        if event is None or event["status"] not in ("OPEN", "LOCKED") or session["status"] != "SCHEDULED":
            fail("ERR_EVENT_NOT_SIGNABLE",
                 "Signup requires event status OPEN or LOCKED and a SCHEDULED session")
    # Priority 7 safety: cross-university sign-up is forbidden.
    if event is not None and student is not None and event["university_id"] != student["university_id"]:
        fail("ERR_CROSS_UNIVERSITY_ACCESS",
             "Student may sign up only for sessions of their own university's events")
    # Priority 8 temporal: exclusive signup deadline.
    if session is not None and not now() < session["signup_deadline"]:
        fail("ERR_SIGNUP_WINDOW_CLOSED", "The signup window has closed")
    # Priority 9 constraint: duplicate guard.
    if event_session_id is not None and student_id is not None:
        duplicate = any(
            s["event_session_id"] == event_session_id
            and s["student_id"] == student_id
            and s["status"] in ("REGISTERED", "WAITLISTED")
            for s in db.all_of("event_signups")
        )
        if duplicate:
            fail("ERR_DUPLICATE_SIGNUP", "An active signup already exists for this student and session")
    body.finalize()
    occupied = sum(
        1 for s in db.all_of("event_signups")
        if s["event_session_id"] == session["id"] and s["status"] == "REGISTERED"
    )
    admitted = occupied < session["capacity"]
    record = {
        "id": db.new_id(),
        "event_session_id": session["id"],
        "student_id": student_id,
        "status": "REGISTERED" if admitted else "WAITLISTED",
        "registered_at": now() if admitted else None,
        "promoted_from_waitlist": False,
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
    }
    db.insert("event_signups", record)
    return success_object(signup_view(record), 201)


@bp.route("/event-signups", methods=["GET"])
def list_signups():
    user_id, role = get_context()
    require_role(role, "Student", "CareerCenterAdmin", "PlatformAdmin")
    records = db.all_of("event_signups")
    if role == "Student":
        records = [s for s in records if s["student_id"] == user_id]
    elif role == "CareerCenterAdmin":
        scoped = []
        for s in records:
            event = _signup_event(s)
            if event is not None and event["university_id"] == user_id:
                scoped.append(s)
        records = scoped
    f_session = request.args.get("event_session_id")
    f_student = request.args.get("student_id")
    f_status = request.args.get("status")
    if f_session is not None:
        records = [s for s in records if s["event_session_id"] == f_session]
    if f_student is not None:
        records = [s for s in records if s["student_id"] == f_student]
    if f_status is not None:
        records = [s for s in records if s["status"] == f_status]
    return paginate(records, signup_view)


@bp.route("/event-signups/<signup_id>", methods=["GET"])
def get_signup(signup_id):
    user_id, role = get_context()
    require_role(role, "Student", "CareerCenterAdmin", "PlatformAdmin")
    signup = db.get("event_signups", signup_id)
    if signup is None:
        fail("ERR_EVENT_SIGNUP_NOT_FOUND", "EventSignup id does not exist")
    if role == "Student" and user_id != signup["student_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Student may read only their own signups")
    if role == "CareerCenterAdmin":
        event = _signup_event(signup)
        if event is None or event["university_id"] != user_id:
            fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may read only its own university's signups")
    return success_object(signup_view(signup))


@bp.route("/event-signups/<signup_id>/transition", methods=["POST"])
def transition_signup(signup_id):
    user_id, role = get_context()
    require_role(role, "Student", "CareerCenterAdmin")
    body = Body()
    to = body.str_f("to", required=True, enum=SIGNUP_STATUSES)
    # Priority 2 per-target role rules.
    if to is not None:
        if role == "Student" and to != "CANCELLED":
            fail("ERR_UNAUTHORIZED_ROLE", "Student may only cancel a signup")
        if role == "CareerCenterAdmin" and to not in ("ATTENDED", "NO_SHOW"):
            fail("ERR_UNAUTHORIZED_ROLE", "Career center may only mark attendance")
    signup = db.get("event_signups", signup_id)
    if signup is None:
        fail("ERR_EVENT_SIGNUP_NOT_FOUND", "EventSignup id does not exist")
    # Priority 3 ownership.
    event = _signup_event(signup)
    if role == "Student" and user_id != signup["student_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Student may transition only their own signups")
    if role == "CareerCenterAdmin" and (event is None or event["university_id"] != user_id):
        fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may mark only its own university's signups")
    # Priority 5 state.
    if to == "CANCELLED":
        if signup["status"] not in ("REGISTERED", "WAITLISTED"):
            fail("ERR_INVALID_SIGNUP_TRANSITION",
                 "Cancellation requires status REGISTERED or WAITLISTED")
    elif to in ("ATTENDED", "NO_SHOW"):
        if signup["status"] != "REGISTERED" or event is None or event["status"] != "COMPLETED":
            fail("ERR_INVALID_SIGNUP_TRANSITION",
                 "Attendance marking requires a REGISTERED signup of a COMPLETED event")
    body.finalize()
    was_registered = signup["status"] == "REGISTERED"
    signup["status"] = to
    db.touch(signup)
    if to == "CANCELLED" and was_registered:
        session = db.get("event_sessions", signup["event_session_id"])
        if session is not None:
            promote_waitlist(session)
    return success_object(signup_view(signup))
