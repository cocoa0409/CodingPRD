"""Rebuild events (PRD 3.6)."""
from flask import Blueprint, request

from db import STORES, new_record
from helpers import (
    body, require_roles, ok_obj, list_response, get_or_404, req_str, req_int,
    req_dt, raise_err, now_iso, parse_date, clock_date,
)
from errors import (
    E_INVALID_REQUEST, E_INVALID_STATE, E_PROJECT_NOT_FOUND, E_EVENT_NOT_FOUND,
    E_EVENT_DATE_PAST, E_EVENT_NOT_LOCKABLE,
)
from logic import (
    bump, compute_posture, event_enrollments, project_items, get_project,
    ACTIVE_ENROLLMENT_STATES, reconciled_cost,
)
from cascades import cancel_event_internal
from serializers import ser_event

bp = Blueprint("events", __name__)

EVENT_STATUSES = ("DRAFT", "PUBLISHED", "LOCKED", "EXECUTED", "CANCELLED")


@bp.post("/rebuild/events")
def create_event():
    require_roles("AffiliateStaff")
    b = body()
    project_id = b.get("project_id")
    if project_id is None:
        raise_err(E_INVALID_REQUEST, 400, "project_id is required")
    project = get_or_404("projects", project_id, E_PROJECT_NOT_FOUND)
    if project["status"] not in ("PLANNING", "READY", "EVENT_SCHEDULED"):
        raise_err(E_INVALID_STATE, 409,
                  "host project must be PLANNING, READY or EVENT_SCHEDULED")
    event_date = req_dt(b, "event_date")
    if parse_date(event_date) < clock_date():
        raise_err(E_EVENT_DATE_PAST, 422,
                  "event_date must be on or after the current date")
    max_volunteers = req_int(b, "max_volunteers")
    if max_volunteers < 1:
        raise_err(E_INVALID_REQUEST, 400, "max_volunteers must be >= 1")
    rec = new_record("events", {
        "project_id": project_id,
        "name": req_str(b, "name"),
        "event_date": event_date,
        "max_volunteers": max_volunteers,
        "status": "DRAFT",
    }, now_iso)
    return ok_obj(ser_event(rec), 201)


@bp.get("/rebuild/events")
def list_events():
    require_roles("Any")
    recs = list(STORES["events"].values())
    pid = request.args.get("project_id")
    if pid is not None:
        recs = [r for r in recs if r["project_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    return list_response(recs, ser_event)


@bp.get("/rebuild/events/<eventId>")
def get_event_route(eventId):
    require_roles("Any")
    rec = get_or_404("events", eventId, E_EVENT_NOT_FOUND)
    return ok_obj(ser_event(rec))


@bp.patch("/rebuild/events/<eventId>")
def patch_event(eventId):
    require_roles("AffiliateStaff")
    rec = get_or_404("events", eventId, E_EVENT_NOT_FOUND)
    b = body()
    if "status" not in b:
        raise_err(E_INVALID_REQUEST, 400, "status is required")
    target = b["status"]
    if not isinstance(target, str) or target not in EVENT_STATUSES:
        raise_err(E_INVALID_REQUEST, 400,
                  "status must be one of " + ", ".join(EVENT_STATUSES))

    if target == "PUBLISHED":
        if rec["status"] != "DRAFT":
            raise_err(E_INVALID_STATE, 409, "event must be DRAFT to publish")
        rec["status"] = "PUBLISHED"
        bump(rec)
    elif target == "LOCKED":
        if rec["status"] != "PUBLISHED":
            raise_err(E_INVALID_STATE, 409, "event must be PUBLISHED to lock")
        project = get_project(rec["project_id"])
        has_leader = any(
            e["is_team_leader"] and e["status"] in ("ENROLLED", "CONFIRMED")
            for e in event_enrollments(rec["id"]))
        if not has_leader:
            raise_err(E_EVENT_NOT_LOCKABLE, 409,
                      "an active team-leader enrollment is required")
        if project is None or compute_posture(project) != "READY":
            raise_err(E_EVENT_NOT_LOCKABLE, 409,
                      "the host project's readiness posture must be READY")
        for e in event_enrollments(rec["id"]):
            if e["status"] == "ENROLLED":
                e["status"] = "CONFIRMED"
                bump(e)
        rec["status"] = "LOCKED"
        bump(rec)
        if project["status"] in ("PLANNING", "READY"):
            project["status"] = "EVENT_SCHEDULED"
            bump(project)
    elif target == "EXECUTED":
        if rec["status"] != "LOCKED":
            raise_err(E_INVALID_STATE, 409, "event must be LOCKED to execute")
        if clock_date() < parse_date(rec["event_date"]):
            raise_err(E_INVALID_STATE, 409,
                      "the event cannot execute before its event_date")
        project = get_project(rec["project_id"])
        # Posture is re-checked at execution time (PRD 3.6): a suspension may
        # have dropped readiness since the event locked.
        if project is None or compute_posture(project) != "READY":
            raise_err(E_INVALID_STATE, 409,
                      "the host project's readiness posture must be READY")
        for e in event_enrollments(rec["id"]):
            if e["status"] == "CHECKED_IN":
                e["status"] = "COMPLETED"
                bump(e)
            elif e["status"] == "CONFIRMED":
                e["status"] = "NO_SHOW"
                bump(e)
        for item in project_items(project):
            if item["status"] == "INCLUDED" and item["volunteer_performable"]:
                item["status"] = "COMPLETED"
        rec["status"] = "EXECUTED"
        bump(rec)
        if project["status"] == "EVENT_SCHEDULED":
            project["status"] = "IN_BUILD"
            bump(project)
    elif target == "CANCELLED":
        if rec["status"] not in ("DRAFT", "PUBLISHED", "LOCKED"):
            raise_err(E_INVALID_STATE, 409,
                      "only DRAFT, PUBLISHED or LOCKED events can be "
                      "cancelled")
        cancel_event_internal(rec)
    else:  # DRAFT is not a drivable target
        raise_err(E_INVALID_STATE, 409, "no transition to %s" % target)
    return ok_obj(ser_event(rec))
