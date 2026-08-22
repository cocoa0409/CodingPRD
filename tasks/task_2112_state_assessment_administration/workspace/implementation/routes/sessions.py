"""Test sessions: scheduling, proctor assignment and the room lifecycle
(PRD 3.3, 3.6)."""

from flask import Blueprint, request

import serialize
from cascades import cancel_session
from db import create, db, now, ordered, touch
from derive import (
    ROOM_TURNOVER_BUFFER_MINUTES,
    SESSION_START_GRACE_MINUTES,
    active_affidavit,
    certification_status,
    outstanding_booklets,
    registrations_of_session,
    seat_pressure_for,
)
from errors import api_error
from middleware import (
    ALL_ROLES,
    PROCTOR,
    SCHOOL_COORDINATOR,
    body_reference,
    endpoint,
    json_body,
    require_scope,
    resolve,
    session_transition_guard,
)
from response import object_response, paginate
from timeutil import plus_minutes
from validators import (
    datetime_field,
    enum_field,
    identifier_field,
    integer_field,
    optional_text,
    string_field,
)

bp = Blueprint("sessions", __name__)

ROOM_CODE_PATTERN = r"[A-Z][0-9]{3}"
SESSION_TYPES = {"INITIAL", "MAKEUP"}
SESSION_TO_STATUS = {"SCHEDULED", "ACTIVE", "CLOSED", "CANCELLED"}

ROOM_OCCUPANCY_STATUSES = ("DRAFT", "SCHEDULED", "ACTIVE", "CLOSED")
PROCTOR_BUSY_STATUSES = ("DRAFT", "SCHEDULED", "ACTIVE")

DECLARED_EDGES = {
    ("DRAFT", "SCHEDULED"),
    ("SCHEDULED", "ACTIVE"),
    ("ACTIVE", "CLOSED"),
    ("DRAFT", "CANCELLED"),
    ("SCHEDULED", "CANCELLED"),
}


def required_phase(session_type):
    return "OPEN" if session_type == "INITIAL" else "MAKEUP"


@bp.post("/sessions")
@endpoint(SCHOOL_COORDINATOR)
def create_session(actor):
    # Check 4 — a session may only be created for the acting school.
    named_school = body_reference("school_id")
    if named_school is not None:
        require_scope(named_school == actor.user_id)

    body = json_body()
    window_id = identifier_field(body, "window_id")
    school_id = identifier_field(body, "school_id")
    room_code = string_field(body, "room_code", pattern=ROOM_CODE_PATTERN)
    scheduled_start = datetime_field(body, "scheduled_start")
    scheduled_end = datetime_field(body, "scheduled_end")
    if not scheduled_end > scheduled_start:
        raise api_error(
            "ERR_INVALID_REQUEST", "scheduled_end must fall strictly after scheduled_start."
        )
    seat_capacity = integer_field(body, "seat_capacity", minimum=1, maximum=400)
    session_type = enum_field(body, "session_type", SESSION_TYPES, required=False, default="INITIAL")

    window = resolve(db.windows, window_id, "ERR_TEST_WINDOW_NOT_FOUND")
    resolve(db.schools, school_id, "ERR_SCHOOL_NOT_FOUND")

    # Check 9 — the window's phase governs which kind of session may be built.
    if window["status"] != required_phase(session_type):
        raise api_error("ERR_WINDOW_PHASE_INVALID")

    # Check 16 — the interval must sit entirely inside the matching phase.
    if session_type == "INITIAL":
        lower, upper = window["window_start"], window["window_end"]
    else:
        lower, upper = window["makeup_start"], window["makeup_end"]
    if scheduled_start < lower or scheduled_end > upper:
        raise api_error("ERR_SESSION_OUTSIDE_WINDOW")

    # Check 17 — room occupancy with the mandatory turnover buffer.
    for existing in db.sessions.values():
        if existing["school_id"] != school_id or existing["room_code"] != room_code:
            continue
        if existing["status"] not in ROOM_OCCUPANCY_STATUSES:
            continue
        if scheduled_start < plus_minutes(
            existing["scheduled_end"], ROOM_TURNOVER_BUFFER_MINUTES
        ) and existing["scheduled_start"] < plus_minutes(
            scheduled_end, ROOM_TURNOVER_BUFFER_MINUTES
        ):
            raise api_error("ERR_ROOM_TIME_CONFLICT")

    session = create(
        db.sessions,
        {
            "window_id": window_id,
            "school_id": school_id,
            "proctor_id": None,
            "room_code": room_code,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "seat_capacity": seat_capacity,
            "session_type": session_type,
            "status": "DRAFT",
            "seats_consumed": 0,
            "effective_seat_capacity": 0,
            "separate_setting_count": 0,
            "materials_checked_out": 0,
            "materials_checked_in": 0,
            "opened_at": None,
            "closed_at": None,
        },
    )
    session.update(seat_pressure_for(session, []))
    return object_response(serialize.session(session), 201)


@bp.get("/sessions/<session_id>")
@endpoint(*ALL_ROLES)
def read_session(actor, session_id):
    session = resolve(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    return object_response(serialize.session(session))


@bp.get("/sessions")
@endpoint(*ALL_ROLES)
def list_sessions(actor):
    window_id = request.args.get("window_id")
    school_id = request.args.get("school_id")
    proctor_id = request.args.get("proctor_id")
    status = request.args.get("status")
    session_type = request.args.get("session_type")
    items = [
        session
        for session in db.sessions.values()
        if (window_id is None or session["window_id"] == window_id)
        and (school_id is None or session["school_id"] == school_id)
        and (proctor_id is None or session["proctor_id"] == proctor_id)
        and (status is None or session["status"] == status)
        and (session_type is None or session["session_type"] == session_type)
    ]
    return paginate(ordered(items), serialize.session)


# --------------------------------------------------------------------------
# Proctor assignment
# --------------------------------------------------------------------------
@bp.post("/sessions/<session_id>/proctor-assignments")
@endpoint(SCHOOL_COORDINATOR)
def assign_proctor(actor, session_id):
    session = resolve(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    require_scope(session["school_id"] == actor.user_id)

    body = json_body()
    proctor_id = identifier_field(body, "proctor_id")
    expected_session_version = integer_field(body, "expected_session_version")

    proctor = resolve(db.proctors, proctor_id, "ERR_PROCTOR_NOT_FOUND")

    # Check 7 — version pinning on the session.
    if expected_session_version != session["version"]:
        raise api_error("ERR_STALE_SESSION_VERSION")

    # Check 8 — assignment is only available while the session is a draft.
    if session["status"] != "DRAFT":
        raise api_error("ERR_INVALID_STATE_TRANSITION")

    # Check 10 and 11 — certification and affidavit.
    if certification_status(proctor) != "CERTIFIED":
        raise api_error("ERR_PROCTOR_NOT_CERTIFIED")
    if active_affidavit(proctor_id, session["window_id"]) is None:
        raise api_error("ERR_AFFIDAVIT_MISSING")

    # Check 18 — closed-interval availability across every school and window.
    for existing in db.sessions.values():
        if existing["id"] == session["id"] or existing["proctor_id"] != proctor_id:
            continue
        if existing["status"] not in PROCTOR_BUSY_STATUSES:
            continue
        if (
            session["scheduled_start"] <= existing["scheduled_end"]
            and existing["scheduled_start"] <= session["scheduled_end"]
        ):
            raise api_error("ERR_PROCTOR_TIME_CONFLICT")

    session["proctor_id"] = proctor_id
    touch(session)
    return object_response(serialize.session(session))


# --------------------------------------------------------------------------
# Lifecycle transitions
# --------------------------------------------------------------------------
@bp.post("/sessions/<session_id>/transitions")
@endpoint(SCHOOL_COORDINATOR, PROCTOR, sub_operation=session_transition_guard)
def transition_session(actor, session_id):
    session = resolve(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    if actor.role == SCHOOL_COORDINATOR:
        require_scope(session["school_id"] == actor.user_id)
    else:
        require_scope(session["proctor_id"] == actor.user_id)

    body = json_body()
    to_status = enum_field(body, "to_status", SESSION_TO_STATUS)
    optional_text(body, "reason")

    current = session["status"]
    if (current, to_status) not in DECLARED_EDGES:
        raise api_error("ERR_INVALID_STATE_TRANSITION")

    if to_status == "SCHEDULED":
        _schedule(session)
    elif to_status == "ACTIVE":
        _activate(session)
    elif to_status == "CLOSED":
        _close(session)
    else:
        _cancel(session)
    return object_response(serialize.session(session))


def _schedule(session):
    if session["proctor_id"] is None:
        raise api_error("ERR_INVALID_STATE_TRANSITION", "the session has no assigned proctor.")
    window = db.windows.get(session["window_id"])
    if window is None or window["status"] != required_phase(session["session_type"]):
        raise api_error("ERR_WINDOW_PHASE_INVALID")
    proctor = db.proctors.get(session["proctor_id"])
    if proctor is None or certification_status(proctor) != "CERTIFIED":
        raise api_error("ERR_PROCTOR_NOT_CERTIFIED")
    if active_affidavit(session["proctor_id"], session["window_id"]) is None:
        raise api_error("ERR_AFFIDAVIT_MISSING")
    session["status"] = "SCHEDULED"
    touch(session)


def _activate(session):
    window = db.windows.get(session["window_id"])
    if window is None or window["status"] != required_phase(session["session_type"]):
        raise api_error("ERR_WINDOW_PHASE_INVALID")

    registrations = registrations_of_session(session["id"])
    seated = [reg for reg in registrations if reg["attendance_status"] != "WITHDRAWN"]
    if outstanding_booklets(session) < len(seated):
        raise api_error("ERR_INSUFFICIENT_MATERIALS")

    moment = now()
    if moment < plus_minutes(session["scheduled_start"], -SESSION_START_GRACE_MINUTES):
        raise api_error("ERR_TIMING_PRECONDITION_NOT_MET")
    if moment > session["scheduled_end"]:
        raise api_error("ERR_TIMING_PRECONDITION_NOT_MET")

    if any(reg["accommodation_status"] == "REQUESTED" for reg in registrations):
        raise api_error("ERR_ACCOMMODATION_NOT_APPROVED")

    session["status"] = "ACTIVE"
    session["opened_at"] = moment
    touch(session)


def _close(session):
    registrations = registrations_of_session(session["id"])
    if any(reg["attendance_status"] == "PENDING" for reg in registrations):
        raise api_error("ERR_INVALID_STATE_TRANSITION", "attendance is still pending on this session.")
    if session["materials_checked_in"] != session["materials_checked_out"]:
        raise api_error("ERR_INVALID_STATE_TRANSITION", "booklets are still checked out to this room.")
    session["status"] = "CLOSED"
    session["closed_at"] = now()
    touch(session)


def _cancel(session):
    if session["materials_checked_out"] != session["materials_checked_in"]:
        raise api_error("ERR_INVALID_STATE_TRANSITION", "the session still holds booklets.")
    cancel_session(session)
