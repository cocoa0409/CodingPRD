"""Readiness session and enrollment endpoints — PRD section 3.5."""

from flask import Blueprint

from common import list_result, match_filters, READ_ROLES, resolve
from counters import sync_session
from domain import (
    ENROLLMENT_STATUSES, SESSION_TYPES, as_dt, enrollments_of_participant,
    enrollments_of_session, rows, sync_participant,
)
from envelope import created, ok
from errors import fail
from store import db, fmt_instant, new_row, now, public, touch
from validation import (
    body, opt_bool, req_enum, req_instant, req_int, req_str, require_roles,
)

bp = Blueprint("sessions", __name__)

MANAGER = ["CaseManager"]
SESSION_TARGETS = ["HELD", "CANCELLED"]
ENROLLMENT_TARGETS = ["ATTENDED", "NO_SHOW", "WITHDRAWN"]


# --------------------------------------------------------------------------
# readiness sessions
# --------------------------------------------------------------------------

@bp.post("/readiness-sessions")
def create_session():
    require_roles(MANAGER)
    payload = body()
    session_type = req_enum(payload, "session_type", SESSION_TYPES)
    coach_user_id = req_str(payload, "coach_user_id")
    starts_at = req_instant(payload, "starts_at")
    ends_at = req_instant(payload, "ends_at")
    seat_capacity = req_int(payload, "seat_capacity", minimum=1, maximum=30)
    if ends_at <= starts_at:
        fail("ERR_VALIDATION", "ends_at must be strictly after starts_at")

    for other in rows(db.sessions):
        if other["status"] != "SCHEDULED":
            continue
        if other["coach_user_id"] != coach_user_id:
            continue
        other_start = as_dt(other["starts_at"])
        other_end = as_dt(other["ends_at"])
        if starts_at < other_end and other_start < ends_at:
            fail("ERR_COACH_DOUBLE_BOOKED",
                 "The coach already facilitates an overlapping session")

    row = new_row(
        session_type=session_type,
        coach_user_id=coach_user_id,
        starts_at=fmt_instant(starts_at),
        ends_at=fmt_instant(ends_at),
        seat_capacity=seat_capacity,
        status="SCHEDULED",
        enrolled_count=0,
        remaining_seats=seat_capacity,
    )
    db.sessions[row["id"]] = row
    return created(public(row))


@bp.get("/readiness-sessions/<session_id>")
def read_session(session_id):
    require_roles(READ_ROLES)
    session = resolve("sessions", db.sessions, session_id)
    return ok(public(session))


@bp.get("/readiness-sessions")
def list_sessions():
    require_roles(READ_ROLES)
    result = match_filters(
        rows(db.sessions),
        string_filters=["status", "session_type", "coach_user_id"],
    )
    return list_result(result)


@bp.post("/readiness-sessions/<session_id>/status")
def drive_session_status(session_id):
    require_roles(MANAGER)
    payload = body()
    to_status = req_enum(payload, "to_status", SESSION_TARGETS)

    session = resolve("sessions", db.sessions, session_id)
    if session["status"] != "SCHEDULED":
        fail("ERR_SESSION_INVALID_STATE",
             "Only a SCHEDULED session may be held or cancelled")
    clock = now()
    if to_status == "HELD":
        if as_dt(session["ends_at"]) > clock:
            fail("ERR_SESSION_INVALID_STATE",
                 "A session cannot be held before it has finished")
        session["status"] = "HELD"
        touch(session)
        for enrollment in enrollments_of_session(session_id):
            if enrollment["status"] == "ENROLLED":
                enrollment["status"] = "NO_SHOW"
                touch(enrollment)
    else:
        if as_dt(session["starts_at"]) <= clock:
            fail("ERR_SESSION_INVALID_STATE",
                 "A session already under way cannot be cancelled")
        session["status"] = "CANCELLED"
        touch(session)
        for enrollment in enrollments_of_session(session_id):
            if enrollment["status"] == "ENROLLED":
                enrollment["status"] = "WITHDRAWN"
                touch(enrollment)
    sync_session(session)
    return ok(public(session))


# --------------------------------------------------------------------------
# enrollments
# --------------------------------------------------------------------------

@bp.post("/readiness-sessions/<session_id>/enrollments")
def create_enrollment(session_id):
    require_roles(MANAGER)
    payload = body()
    participant_id = req_str(payload, "participant_id")
    reviewed = opt_bool(payload, "disclosure_script_reviewed", default=False)

    session = resolve("sessions", db.sessions, session_id)
    if participant_id not in db.participants:
        fail("ERR_PARTICIPANT_NOT_FOUND", "participant_id matches no participant")
    participant = db.participants[participant_id]

    if session["status"] != "SCHEDULED":
        fail("ERR_SESSION_INVALID_STATE",
             "Only a SCHEDULED session accepts enrollments")
    if participant["suspension_status"] == "SUSPENDED":
        fail("ERR_PARTICIPANT_SUSPENDED",
             "A suspended participant may not be enrolled")
    if as_dt(session["starts_at"]) <= now():
        fail("ERR_SESSION_ALREADY_STARTED",
             "The session has already started")
    if int(session["remaining_seats"]) <= 0:
        fail("ERR_SESSION_FULL", "The session has no remaining seats")
    for existing in enrollments_of_session(session_id):
        if (existing["participant_id"] == participant_id
                and existing["status"] in ("ENROLLED", "ATTENDED", "NO_SHOW")):
            fail("ERR_DUPLICATE_ENROLLMENT",
                 "The participant already holds an enrollment on this session")

    row = new_row(
        session_id=session_id,
        participant_id=participant_id,
        status="ENROLLED",
        disclosure_script_reviewed=reviewed,
    )
    db.enrollments[row["id"]] = row
    sync_session(session)
    return created(public(row))


@bp.get("/readiness-sessions/<session_id>/enrollments")
def list_session_enrollments(session_id):
    require_roles(READ_ROLES)
    resolve("sessions", db.sessions, session_id)
    result = match_filters(enrollments_of_session(session_id),
                           string_filters=["status"])
    return list_result(result)


@bp.get("/enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    require_roles(READ_ROLES)
    enrollment = resolve("enrollments", db.enrollments, enrollment_id)
    return ok(public(enrollment))


@bp.get("/enrollments")
def list_enrollments():
    require_roles(READ_ROLES)
    result = match_filters(
        rows(db.enrollments),
        string_filters=["session_id", "participant_id", "status"],
    )
    return list_result(result)


@bp.post("/enrollments/<enrollment_id>/status")
def drive_enrollment_status(enrollment_id):
    require_roles(MANAGER)
    payload = body()
    to_status = req_enum(payload, "to_status", ENROLLMENT_TARGETS)

    enrollment = resolve("enrollments", db.enrollments, enrollment_id)
    if enrollment["status"] != "ENROLLED":
        fail("ERR_ENROLLMENT_INVALID_STATE",
             "Only an ENROLLED enrollment may transition")

    session = db.sessions.get(enrollment["session_id"])
    clock = now()
    if to_status in ("ATTENDED", "NO_SHOW"):
        if session is None or session["status"] not in ("SCHEDULED", "HELD"):
            fail("ERR_SESSION_INVALID_STATE",
                 "Attendance may only be recorded on a scheduled or held session")
        if as_dt(session["starts_at"]) > clock:
            fail("ERR_SESSION_INVALID_STATE",
                 "The session has not started yet")
    else:
        if session is None or session["status"] != "SCHEDULED":
            fail("ERR_SESSION_INVALID_STATE",
                 "Withdrawal requires a SCHEDULED session")

    enrollment["status"] = to_status
    touch(enrollment)
    if to_status == "WITHDRAWN":
        sync_session(session)
    participant = db.participants.get(enrollment["participant_id"])
    if participant is not None:
        sync_participant(participant)
    return ok(public(enrollment))
