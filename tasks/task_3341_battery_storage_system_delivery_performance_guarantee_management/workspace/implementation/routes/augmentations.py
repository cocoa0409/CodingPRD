"""AugmentationEvent routes: plan/list/get/execute/cancel."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles, ALL_ROLES
from pagination import paginate
from response import success_object, success_list
from services import recompute_projection, recompute_augmentation_count
from util import new_id, stamp_new, touch, parse_iso, req_pos_number

bp = Blueprint("augmentations", __name__)


def serialize_event(e):
    return dict(e)


def get_event_or_404(eid):
    e = store.augmentations.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "AugmentationEvent not found")
    return e


@bp.route("/augmentation-events", methods=["POST"])
@require_roles({"ServiceEngineer"})
def create_event():
    body = request.get_json(silent=True) or {}
    project_id = body.get("project_id")
    if not isinstance(project_id, str) or project_id not in store.projects:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "project_id does not reference an existing Project")
    project = store.projects[project_id]
    added = req_pos_number(body, "added_capacity_mwh")
    ws_raw = body.get("planned_window_start")
    we_raw = body.get("planned_window_end")
    ws = parse_iso(ws_raw, "planned_window_start")
    we = parse_iso(we_raw, "planned_window_end")
    if we <= ws:
        raise ApiError("ERR_INVALID_WINDOW", 409,
                       "planned_window_end must be strictly after planned_window_start")
    if not project.get("commissioned_capacity_mwh") or project["commissioned_capacity_mwh"] <= 0:
        raise ApiError("ERR_PROJECT_NOT_COMMISSIONED", 409,
                       "Manual augmentation requires Project.commissioned_capacity_mwh > 0")
    e = {
        "id": new_id(),
        "project_id": project_id,
        "planned_window_start": ws_raw,
        "planned_window_end": we_raw,
        "added_capacity_mwh": added,
        "origin": "MANUAL",
        "status": "PLANNED",
    }
    stamp_new(e)
    store.augmentations[e["id"]] = e
    recompute_augmentation_count(project)
    touch(project)
    return success_object(serialize_event(e), 201)


@bp.route("/augmentation-events", methods=["GET"])
@require_roles(set(ALL_ROLES))
def list_events():
    project_id = request.args.get("project_id")
    items = [e for e in store.augmentations.values()
             if project_id is None or e["project_id"] == project_id]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_event(e) for e in page], limit, offset, total)


@bp.route("/augmentation-events/<eid>", methods=["GET"])
@require_roles(set(ALL_ROLES))
def get_event(eid):
    return success_object(serialize_event(get_event_or_404(eid)))


@bp.route("/augmentation-events/<eid>/execute", methods=["POST"])
@require_roles({"ServiceEngineer"})
def execute_event(eid):
    e = get_event_or_404(eid)
    project = store.projects.get(e["project_id"])
    body = request.get_json(silent=True) or {}
    expected = body.get("expected_project_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise ApiError("ERR_INVALID_REQUEST", 400, "expected_project_version must be an integer")
        if expected != project["version"]:
            raise ApiError("ERR_STALE_PROJECT_VERSION", 412,
                           "expected_project_version does not equal the Project's current version")
    if e["status"] != "PLANNED":
        raise ApiError("ERR_AUGMENTATION_NOT_PLANNED", 409, "Event must be PLANNED")
    now = store.clock()
    ws = parse_iso(e["planned_window_start"], "planned_window_start")
    we = parse_iso(e["planned_window_end"], "planned_window_end")
    if not (ws <= now < we):
        raise ApiError("ERR_AUGMENTATION_WINDOW_NOT_OPEN", 409,
                       "Logical clock must be within [planned_window_start, planned_window_end)")
    e["status"] = "EXECUTED"
    touch(e)
    recompute_projection(project)
    recompute_augmentation_count(project)
    touch(project)
    return success_object(serialize_event(e))


@bp.route("/augmentation-events/<eid>/cancel", methods=["POST"])
@require_roles({"ServiceEngineer"})
def cancel_event(eid):
    e = get_event_or_404(eid)
    if e["status"] != "PLANNED":
        raise ApiError("ERR_AUGMENTATION_NOT_PLANNED", 409, "Event must be PLANNED")
    e["status"] = "CANCELLED"
    touch(e)
    project = store.projects.get(e["project_id"])
    if project is not None:
        recompute_augmentation_count(project)
        touch(project)
    return success_object(serialize_event(e))
