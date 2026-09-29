"""Development-project reads, feasibility, abandonment and turnaround."""

from flask import Blueprint, request

import domain as d
from auth import (ROLE_BUSINESS_AFFAIRS, ROLE_DEV_EXEC, ROLE_FINANCE,
                  ROLE_PLATFORM_ADMIN, ROLE_RESEARCH, ROLE_STUDIO, authorize)
from errors import ApiError
from responses import object_response, paginated
from store import new_row, store, touch
from validators import json_body, query_int, require_body, v_string

bp = Blueprint("project", __name__)

PROJECT_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS,
                      ROLE_FINANCE)


@bp.get("/development-projects/<project_id>")
@authorize(*PROJECT_READ_ROLES)
def read_project(principal, project_id):
    row = d.get_project(project_id)
    return object_response(d.serialize_project(row))


@bp.get("/development-projects")
@authorize(*PROJECT_READ_ROLES)
def list_projects(principal):
    rows = d.ordered(list(store.projects.values()))
    pitch_id = request.args.get("pitch_id")
    if pitch_id is not None:
        rows = [r for r in rows if r["pitch_id"] == pitch_id]
    slate_id = request.args.get("slate_id")
    if slate_id is not None:
        rows = [r for r in rows if r["slate_id"] == slate_id]
    predecessor = request.args.get("predecessor_project_id")
    if predecessor is not None:
        rows = [r for r in rows if r["predecessor_project_id"] == predecessor]
    dev_status = request.args.get("dev_status")
    if dev_status is not None:
        rows = [r for r in rows if r["dev_status"] == dev_status]
    return paginated(rows, d.serialize_project)


@bp.get("/development-projects/<project_id>/feasibility")
@authorize(ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS, ROLE_FINANCE)
def read_feasibility(principal, project_id):
    project = d.get_project(project_id)
    slate = d.slate_of_project(project)

    basis = request.args.get("basis")
    if basis is None:
        basis = "PATTERN"
    elif basis not in d.FEASIBILITY_BASES:
        raise ApiError("ERR_INVALID_REQUEST", "basis must be PATTERN or LICENSE.")

    episode_count = query_int("episode_count", minimum=1)
    if episode_count is None:
        episode_count = slate["default_episode_count"]
    return object_response(d.feasibility(project, basis, episode_count))


@bp.get("/development-projects/<project_id>/pilot-orders")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS, ROLE_RESEARCH)
def list_project_pilots(principal, project_id):
    project = d.get_project(project_id)
    return paginated(d.pilots_of_project(project), d.serialize_pilot_order)


@bp.get("/development-projects/<project_id>/negotiations")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS, ROLE_FINANCE,
           ROLE_STUDIO)
def list_project_negotiations(principal, project_id):
    project = d.get_project(project_id)
    rows = d.negotiations_of_project(project)
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, d.serialize_negotiation)


# ---------------------------------------------------------------------------
# abandonment and turnaround
# ---------------------------------------------------------------------------

ABANDONABLE = ("ACTIVE_DEVELOPMENT", "SCRIPT_COMPLETE", "PILOT_ORDERED",
               "PILOT_DELIVERED")


@bp.post("/development-projects/<project_id>/abandon")
@authorize(ROLE_DEV_EXEC)
def abandon_project(principal, project_id):
    project = d.get_project(project_id)
    body = require_body(json_body())
    reason = v_string(body, "abandon_reason", max_len=500)
    if project["dev_status"] not in ABANDONABLE:
        raise ApiError("ERR_INVALID_PROJECT_STATE")
    d.cascade_abandon(project, reason)
    return object_response(d.serialize_project(project))


@bp.post("/development-projects/<project_id>/turnaround")
@authorize(ROLE_BUSINESS_AFFAIRS)
def offer_turnaround(principal, project_id):
    project = d.get_project(project_id)
    if project["dev_status"] != "ABANDONED":
        raise ApiError("ERR_INVALID_PROJECT_STATE")
    if project["turnaround_status"] != "NONE":
        raise ApiError("ERR_INVALID_PROJECT_STATE")
    project["turnaround_status"] = "OFFERED"
    project["turnaround_offered_at"] = store.now()
    touch(project)
    return object_response(d.serialize_project(project))


@bp.post("/development-projects/<project_id>/turnaround-exercise")
@authorize(ROLE_BUSINESS_AFFAIRS)
def exercise_turnaround(principal, project_id):
    project = d.get_project(project_id)
    body = require_body(json_body())
    successor_title = v_string(body, "successor_title", max_len=160)

    if project["turnaround_status"] != "OFFERED":
        raise ApiError("ERR_INVALID_PROJECT_STATE")
    # 32 -- the 180-day window must still be open.
    if not d.turnaround_window_open(project):
        raise ApiError("ERR_TURNAROUND_WINDOW_CLOSED")

    project["recoupment_paid_cents"] = d.recoupment_at_clock(project)
    project["turnaround_status"] = "EXERCISED"
    touch(project)

    slate = d.slate_of_project(project)
    successor = new_row(
        pitch_id=project["pitch_id"],
        slate_id=project["slate_id"],
        predecessor_project_id=project["id"],
        title=successor_title,
        dev_status="ACTIVE_DEVELOPMENT",
        turnaround_status="NONE",
        turnaround_offered_at=None,
        writeoff_cents=0,
        abandoned_at=None,
        abandon_reason=None,
        recoupment_paid_cents=0,
    )
    store.projects[successor["id"]] = successor
    touch(slate)
    return object_response(d.serialize_project(successor), 201)
