"""Interview sessions: scheduling, holding, postponement."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import svc
from core import (
    ApiError,
    D,
    body,
    db,
    dump,
    endpoint,
    f_dt,
    f_enum,
    f_str,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("sessions", __name__)


def _notice_decimal(hours):
    return calc.rhu(D(hours), 2)


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
@bp.post("/investigations/<investigation_id>/interview-sessions")
@endpoint("Investigator")
def create_session(investigation_id):
    investigation = svc.need_investigation(investigation_id)
    payload = body()
    # tier 4 -- schema
    subject_officer_id = f_str(payload, "subject_officer_id")
    hearing_room_id = f_str(payload, "hearing_room_id")
    scheduled_start = f_dt(payload, "scheduled_start")
    scheduled_end = f_dt(payload, "scheduled_end")
    notice_served_at = f_dt(payload, "notice_served_at")
    representation_status = f_enum(
        payload,
        "representation_status",
        calc.REPRESENTATION_STATUSES,
        required=False,
        default="REP_REQUESTED",
    )
    # tier 5 -- body reference existence
    subject = svc.need_officer(subject_officer_id)
    room = svc.need_room(hearing_room_id)
    # tier 6 -- resource-level ownership
    if investigation.get("assigned_investigator_officer_id") != g.user_id:
        raise ApiError("ERR_NOT_ASSIGNED_INVESTIGATOR")
    # tier 8 -- state legality
    if investigation["status"] not in ("ASSIGNED", "IN_PROGRESS"):
        raise ApiError("ERR_INVESTIGATION_NOT_INTERVIEWABLE")
    if subject["employment_status"] == "SEPARATED":
        raise ApiError("ERR_OFFICER_SEPARATED")
    # tier 9 -- business safety
    notice_hours = calc.notice_hours(notice_served_at, scheduled_start)
    if notice_hours < calc.MIN_NOTICE_HOURS:
        raise ApiError("ERR_INSUFFICIENT_NOTICE")
    # tier 11 -- temporal rules
    if not (scheduled_end > scheduled_start and scheduled_start > db.clock):
        raise ApiError("ERR_INVALID_SESSION_WINDOW")
    if calc.officer_buffer_conflict(subject_officer_id, scheduled_start, scheduled_end):
        raise ApiError("ERR_OFFICER_REST_BUFFER_CONFLICT")
    overlaps = calc.room_overlap_count(hearing_room_id, scheduled_start, scheduled_end)
    if not (overlaps < room["concurrent_capacity"]):
        raise ApiError("ERR_ROOM_CAPACITY_EXCEEDED")

    session = new_row(
        "InterviewSession",
        investigation_id=investigation["id"],
        subject_officer_id=subject_officer_id,
        hearing_room_id=hearing_room_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        notice_served_at=notice_served_at,
        notice_hours=_notice_decimal(notice_hours),
        representation_status=representation_status,
        status="SCHEDULED",
        postpone_count=0,
        held_at=None,
        duration_minutes=calc.duration_minutes(scheduled_start, scheduled_end),
        interview_summary=None,
    )
    db.sessions[session["id"]] = session
    if investigation["status"] == "ASSIGNED":
        investigation["status"] = "IN_PROGRESS"
        touch(investigation)
    return respond_object(dump(session), 201)


@bp.get("/interview-sessions/<session_id>")
@endpoint("Investigator", "IACommander", "OfficerRepresentative", "RecordsCustodian")
def read_session(session_id):
    return respond_object(dump(svc.need_session(session_id)))


@bp.get("/interview-sessions")
@endpoint("Investigator", "IACommander", "OfficerRepresentative", "RecordsCustodian")
def list_sessions():
    investigation_id = q_str("investigation_id")
    subject_officer_id = q_str("subject_officer_id")
    hearing_room_id = q_str("hearing_room_id")
    status = q_enum("status", calc.SESSION_STATUSES)
    rows = sort_created(list(db.sessions.values()))
    if investigation_id is not None:
        rows = [r for r in rows if r["investigation_id"] == investigation_id]
    if subject_officer_id is not None:
        rows = [r for r in rows if r["subject_officer_id"] == subject_officer_id]
    if hearing_room_id is not None:
        rows = [r for r in rows if r["hearing_room_id"] == hearing_room_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows)


# ---------------------------------------------------------------------------
# Hold
# ---------------------------------------------------------------------------
@bp.post("/interview-sessions/<session_id>/hold")
@endpoint("Investigator")
def hold_session(session_id):
    session = svc.need_session(session_id)
    payload = body()
    interview_summary = f_str(payload, "interview_summary")
    supplied_rep = f_enum(
        payload, "representation_status", calc.REPRESENTATION_STATUSES, required=False
    )
    investigation = db.investigations.get(session["investigation_id"])
    subject = db.officers.get(session["subject_officer_id"])
    # tier 6 -- resource-level ownership
    if (
        investigation is None
        or investigation.get("assigned_investigator_officer_id") != g.user_id
    ):
        raise ApiError("ERR_NOT_ASSIGNED_INVESTIGATOR")
    # tier 8 -- state legality
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_STATE_INVALID")
    if subject is not None and subject["employment_status"] == "SEPARATED":
        raise ApiError("ERR_OFFICER_SEPARATED")
    # tier 9 -- business safety
    notice_hours = calc.notice_hours(
        session["notice_served_at"], session["scheduled_start"]
    )
    if notice_hours < calc.MIN_NOTICE_HOURS:
        raise ApiError("ERR_INSUFFICIENT_NOTICE")
    effective_rep = supplied_rep or session["representation_status"]
    if effective_rep not in ("WAIVED", "REP_PRESENT"):
        raise ApiError("ERR_REPRESENTATION_NOT_PRESENT")
    # tier 11 -- temporal rules
    if db.clock < session["scheduled_start"]:
        raise ApiError("ERR_INTERVIEW_NOT_STARTED")

    session["representation_status"] = effective_rep
    session["interview_summary"] = interview_summary
    session["status"] = "HELD"
    session["held_at"] = db.clock
    touch(session)
    investigation["interview_held_count"] += 1
    if investigation["status"] == "ASSIGNED":
        investigation["status"] = "IN_PROGRESS"
    touch(investigation)
    return respond_object(dump(session))


# ---------------------------------------------------------------------------
# Postpone
# ---------------------------------------------------------------------------
@bp.post("/interview-sessions/<session_id>/postpone")
@endpoint("Investigator", "OfficerRepresentative")
def postpone_session(session_id):
    session = svc.need_session(session_id)
    payload = body()
    new_start = f_dt(payload, "new_scheduled_start")
    new_end = f_dt(payload, "new_scheduled_end")
    new_notice = f_dt(payload, "new_notice_served_at")
    f_str(payload, "postpone_reason")
    room_id = f_str(payload, "hearing_room_id", required=False)
    # tier 5 -- body reference existence
    if room_id is not None:
        room = svc.need_room(room_id)
    else:
        room_id = session["hearing_room_id"]
        room = svc.need_room(room_id)
    # tier 8 -- state legality
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_STATE_INVALID")
    # tier 9 -- business safety
    notice_hours = calc.notice_hours(new_notice, new_start)
    if notice_hours < calc.MIN_NOTICE_HOURS:
        raise ApiError("ERR_INSUFFICIENT_NOTICE")
    # tier 11 -- temporal rules
    if not (new_end > new_start and new_start > db.clock):
        raise ApiError("ERR_INVALID_SESSION_WINDOW")
    if calc.officer_buffer_conflict(
        session["subject_officer_id"], new_start, new_end, exclude_session_id=session["id"]
    ):
        raise ApiError("ERR_OFFICER_REST_BUFFER_CONFLICT")
    overlaps = calc.room_overlap_count(
        room_id, new_start, new_end, exclude_session_id=session["id"]
    )
    if not (overlaps < room["concurrent_capacity"]):
        raise ApiError("ERR_ROOM_CAPACITY_EXCEEDED")
    # tier 12 -- business constraints
    if session["postpone_count"] >= calc.MAX_POSTPONEMENTS:
        raise ApiError("ERR_MAX_POSTPONEMENTS_REACHED")

    session["postpone_count"] += 1
    session["hearing_room_id"] = room_id
    session["scheduled_start"] = new_start
    session["scheduled_end"] = new_end
    session["notice_served_at"] = new_notice
    session["notice_hours"] = _notice_decimal(notice_hours)
    session["duration_minutes"] = calc.duration_minutes(new_start, new_end)
    session["status"] = "SCHEDULED"
    touch(session)
    return respond_object(dump(session))
