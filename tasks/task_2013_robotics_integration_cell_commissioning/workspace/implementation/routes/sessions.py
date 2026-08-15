"""TrainingSession endpoints (PRD §3.8)."""
from flask import Blueprint, request

from db import children, store
from errors import (ApiError, ERR_FORBIDDEN_ROLE, ERR_OUTSIDE_SESSION_WINDOW,
                    ERR_TRAINER_SCHEDULE_CONFLICT, invalid_state, not_found)
from middleware import authenticate
from middleware import ROLE_FINANCE_ADMIN as FA
from middleware import ROLE_PROJECT_ENGINEER as PE
from middleware import ROLE_SITE_SUPERVISOR as SS
from middleware import ROLE_TRAINER as TR
from response import success, success_list
from services import calculations as calc
from services.domain import common_fields, pub, pubs, touch
from timeutil import fmt_dt, parse_dt
from validation import (as_dt, as_enum, as_int, as_num, as_str, body, paginate,
                        pagination, req)

bp = Blueprint("sessions", __name__)

READ_ROLES = {FA, PE, SS, TR}
AUDIENCES = ("OPERATOR", "TECHNICIAN")


def get_session(session_id):
    s = store.sessions.get(session_id)
    if s is None:
        raise not_found("Training session not found")
    return s


@bp.post("/robotics/cell-projects/<project_id>/training-sessions")
def create_session(project_id):
    authenticate({TR})
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    b = body()
    # Trainer scheduling (priority 12) evaluates before generic field checks (18).
    raw_start = b.get("scheduled_start_utc")
    raw_end = b.get("scheduled_end_utc")
    if raw_start is not None and raw_end is not None:
        start = parse_dt(raw_start, "scheduled_start_utc")
        end = parse_dt(raw_end, "scheduled_end_utc")
        if not end > start:
            raise ApiError(ERR_TRAINER_SCHEDULE_CONFLICT, 422,
                           "scheduled_end_utc must be strictly after scheduled_start_utc")
        trainer = b.get("trainer_user_id")
        for other in store.sessions.values():
            if other["trainer_user_id"] != trainer:
                continue
            if other["session_status"] not in ("SCHEDULED", "IN_PROGRESS"):
                continue
            o_start = parse_dt(other["scheduled_start_utc"], "scheduled_start_utc")
            o_end = parse_dt(other["scheduled_end_utc"], "scheduled_end_utc")
            # Half-open [start, end) overlap: back-to-back adjacency is allowed.
            if start < o_end and o_start < end:
                raise ApiError(ERR_TRAINER_SCHEDULE_CONFLICT, 422,
                               "Trainer is already booked on an overlapping session")
    audience = as_enum(req(b, "audience"), "audience", AUDIENCES)
    start = as_dt(req(b, "scheduled_start_utc"), "scheduled_start_utc")
    end = as_dt(req(b, "scheduled_end_utc"), "scheduled_end_utc")
    trainer = as_str(req(b, "trainer_user_id"), "trainer_user_id")
    attendees = as_int(req(b, "attendee_count"), "attendee_count", 1, 12)
    session = {
        **common_fields(),
        "cell_project_id": project_id,
        "audience": audience,
        "scheduled_start_utc": fmt_dt(start),
        "scheduled_end_utc": fmt_dt(end),
        "trainer_user_id": trainer,
        "attendee_count": attendees,
        "completion_score_pct": None,
        "practical_score_pct": None,
        "written_score_pct": None,
        "session_status": "SCHEDULED",
    }
    store.sessions[session["id"]] = session
    return success(pub(session), 201)


@bp.get("/robotics/cell-projects/<project_id>/training-sessions")
def list_sessions(project_id):
    authenticate(READ_ROLES)
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    limit, offset = pagination()
    items = children("sessions", "cell_project_id", project_id)
    audience = request.args.get("audience")
    if audience is not None:
        items = [s for s in items if s["audience"] == audience]
    status_filter = request.args.get("session_status")
    if status_filter is not None:
        items = [s for s in items if s["session_status"] == status_filter]
    trainer = request.args.get("trainer_user_id")
    if trainer is not None:
        items = [s for s in items if s["trainer_user_id"] == trainer]
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/training-sessions/<session_id>")
def get_one_session(session_id):
    authenticate(READ_ROLES)
    return success(pub(get_session(session_id)))


@bp.post("/robotics/training-sessions/<session_id>/start")
def start_session(session_id):
    authenticate({TR})
    s = get_session(session_id)
    if s["session_status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED session can be started")
    project = store.projects[s["cell_project_id"]]
    if project["status"] != "TRAINING":
        raise invalid_state("Starting a session requires project status TRAINING")
    clock = store.logical_clock
    start = parse_dt(s["scheduled_start_utc"], "scheduled_start_utc")
    end = parse_dt(s["scheduled_end_utc"], "scheduled_end_utc")
    if not (start <= clock <= end):  # both ends inclusive (PRD §3.8)
        raise ApiError(ERR_OUTSIDE_SESSION_WINDOW, 422,
                       "Logical clock is outside the scheduled session window")
    s["session_status"] = "IN_PROGRESS"
    touch(s)
    return success(pub(s))


@bp.post("/robotics/training-sessions/<session_id>/complete")
def complete_session(session_id):
    uid, _role = authenticate({TR})
    s = get_session(session_id)
    if s["session_status"] != "IN_PROGRESS":
        raise invalid_state("Only an IN_PROGRESS session can be completed")
    if uid != s["trainer_user_id"]:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                       "Only the session's assigned trainer may score it")
    b = body()
    practical = as_num(req(b, "practical_score_pct"), "practical_score_pct", 0, 100)
    written = as_num(req(b, "written_score_pct"), "written_score_pct", 0, 100)
    s["practical_score_pct"] = practical
    s["written_score_pct"] = written
    s["completion_score_pct"] = calc.training_completion(s["audience"], practical, written)
    s["session_status"] = "COMPLETED"
    touch(s)
    return success(pub(s))


@bp.post("/robotics/training-sessions/<session_id>/cancel")
def cancel_session(session_id):
    authenticate({TR})
    s = get_session(session_id)
    if s["session_status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED session can be cancelled")
    s["session_status"] = "CANCELLED"
    touch(s)
    return success(pub(s))
