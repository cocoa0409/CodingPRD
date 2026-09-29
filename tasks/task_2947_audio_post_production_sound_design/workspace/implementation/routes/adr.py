"""ADR sessions (PRD §3.5)."""

from decimal import Decimal

from flask import Blueprint

import calc
import clock
import derive
import middleware
import response
import serialize
import validation as V
from db import db, new_record, newest_first, touch
from errors import ApiError

bp = Blueprint("adr", __name__)

OVERLAP_STATUSES = ("PROPOSED", "CONFIRMED", "RECORDED")
DAILY_CAP_STATUSES = ("PROPOSED", "CONFIRMED", "RECORDED", "NO_SHOW")


def _sessions_of_talent(talent_id):
    return [s for s in db.adr_sessions.values() if s["voice_talent_id"] == talent_id]


@bp.post("/adr-sessions")
def create_adr_session():
    middleware.actor("SoundEditor", "PostSupervisor")
    payload = V.body()
    project = middleware.body_ref(payload, "project_id", db.projects)
    talent = middleware.body_ref(payload, "voice_talent_id", db.voice_talents)
    V.v_string(payload, "project_id", minlen=1)
    V.v_string(payload, "voice_talent_id", minlen=1)
    window_start = V.v_instant(payload, "window_start_utc")
    window_end = V.v_instant(payload, "window_end_utc")
    lines_scheduled = V.v_int(payload, "lines_scheduled", minv=1)
    middleware.gate_archived(project)
    middleware.gate_picture_locked(project)
    if window_end <= window_start:
        raise ApiError("ERR_WINDOW_INVALID")
    if window_end > project["delivery_deadline_utc"]:
        raise ApiError("ERR_WINDOW_AFTER_DEADLINE")

    scheduled, billable, cost = calc.adr_session_cost(
        window_start, window_end, talent["union_status"], talent["min_call_minutes"])

    # Rung 34: strict overlap with another live session of the same talent.
    for other in _sessions_of_talent(talent["id"]):
        if other["status"] not in OVERLAP_STATUSES:
            continue
        if window_start < other["window_end_utc"] and other["window_start_utc"] < window_end:
            raise ApiError("ERR_TALENT_WINDOW_CONFLICT")

    # Rung 35: same-UTC-day billable minutes against the talent's daily cap.
    day = window_start.date()
    same_day = Decimal("0.00")
    for other in _sessions_of_talent(talent["id"]):
        if other["status"] not in DAILY_CAP_STATUSES:
            continue
        if other["window_start_utc"].date() != day:
            continue
        same_day = same_day + other["billable_minutes"]
    if same_day + billable > Decimal(talent["daily_cap_minutes"]):
        raise ApiError("ERR_TALENT_DAILY_CAP_EXCEEDED")

    record = new_record()
    record.update({
        "project_id": project["id"],
        "voice_talent_id": talent["id"],
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "lines_scheduled": lines_scheduled,
        "lines_recorded": 0,
        "status": "PROPOSED",
        "scheduled_minutes": scheduled,
        "billable_minutes": billable,
        "session_cost_cents": cost,
        "cancellation_reason": None,
    })
    db.adr_sessions[record["id"]] = record
    return response.object_response(serialize.adr_session(record), 201)


@bp.get("/adr-sessions/<session_id>")
def read_adr_session(session_id):
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "QcOperator")
    record = middleware.path_adr_session(session_id)
    return response.object_response(serialize.adr_session(record))


@bp.get("/adr-sessions")
def list_adr_sessions():
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "QcOperator")
    limit, offset = V.pagination()
    project_id = V.query_filter("project_id")
    voice_talent_id = V.query_filter("voice_talent_id")
    status = V.query_filter("status")
    records = list(db.adr_sessions.values())
    if project_id is not None:
        records = [r for r in records if r["project_id"] == project_id]
    if voice_talent_id is not None:
        records = [r for r in records if r["voice_talent_id"] == voice_talent_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = newest_first(records)
    window, total = response.paginate(records, limit, offset)
    return response.list_response([serialize.adr_session(r) for r in window],
                                  limit, offset, total)


@bp.post("/adr-sessions/<session_id>/confirm")
def confirm_adr_session(session_id):
    """PRD §3.5: PROPOSED -> CONFIRMED; the cost enters adr_cost_cents."""
    middleware.actor("SoundEditor")
    session = middleware.path_adr_session(session_id)
    project = db.projects.get(session["project_id"])
    middleware.gate_posture(project, "adr_confirm")
    middleware.gate_archived(project)
    middleware.gate_picture_locked(project)
    if session["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE")

    session["status"] = "CONFIRMED"
    touch(session)
    derive.recompute_project(project)
    derive.touch_project(project)
    return response.object_response(serialize.adr_session(session))


@bp.post("/adr-sessions/<session_id>/record")
def record_adr_session(session_id):
    """PRD §3.5: CONFIRMED -> RECORDED; adr_cost_cents is unchanged."""
    middleware.actor("SoundEditor")
    session = middleware.path_adr_session(session_id)
    payload = V.body()
    lines_recorded = V.v_int(payload, "lines_recorded", minv=0)
    project = db.projects.get(session["project_id"])
    middleware.gate_posture(project, "adr_record")
    middleware.gate_archived(project)
    if session["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE")
    if clock.now() < session["window_start_utc"]:
        raise ApiError("ERR_INVALID_STATE")
    if lines_recorded > session["lines_scheduled"]:
        raise ApiError("ERR_ADR_LINES_EXCEEDED")

    session["status"] = "RECORDED"
    session["lines_recorded"] = lines_recorded
    touch(session)
    return response.object_response(serialize.adr_session(session))


@bp.post("/adr-sessions/<session_id>/cancel")
def cancel_adr_session(session_id):
    """PRD §3.5: CLIENT_REQUEST|SCHEDULE_CONFLICT -> CANCELLED, TALENT_NO_SHOW ->
    NO_SHOW (the cost stays inside adr_cost_cents)."""
    middleware.actor("SoundEditor", "PostSupervisor")
    session = middleware.path_adr_session(session_id)
    payload = V.body()
    reason = V.v_enum(payload, "cancellation_reason", V.CANCELLATION_REASONS)
    project = db.projects.get(session["project_id"])
    middleware.gate_archived(project)

    if reason == "TALENT_NO_SHOW":
        if session["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE")
        if clock.now() < session["window_start_utc"]:
            raise ApiError("ERR_INVALID_STATE")
        session["status"] = "NO_SHOW"
        session["cancellation_reason"] = reason
        touch(session)
        return response.object_response(serialize.adr_session(session))

    if session["status"] not in ("PROPOSED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE")
    was_confirmed = session["status"] == "CONFIRMED"
    session["status"] = "CANCELLED"
    session["cancellation_reason"] = reason
    touch(session)
    if was_confirmed:
        derive.recompute_project(project)
        derive.touch_project(project)
    return response.object_response(serialize.adr_session(session))
