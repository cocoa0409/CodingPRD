"""Overnight grooming: planning, dispatch sequencing and coverage (PRD 3.3)."""
from flask import Blueprint

import db
import response
import validate
from errors import ApiError
from middleware import auth, ALL_ROLES, GROOMING_LEAD
from services import calc, cascade, serialize

bp = Blueprint("grooming", __name__)

DISPATCHABLE = ("PLANNED", "DEFERRED")
BLOCKED_TERRAIN = ("PATROL_HOLD", "SEASON_CLOSED")
UNFINISHED = ("PLANNED", "DISPATCHED", "DEFERRED")


@bp.route("/grooming-tasks", methods=["POST"])
def create_task():
    auth(GROOMING_LEAD)
    body = validate.body()
    # Priority 4.
    area = validate.fk(body, "terrain_area_id", db.store.areas,
                       "ERR_TERRAIN_AREA_NOT_FOUND")
    # Priority 5.
    validate.get_str(body, "terrain_area_id")
    route_code = validate.get_str(body, "cat_route_code", max_len=24)
    sequence_index = validate.get_int(body, "sequence_index", minimum=1)
    unit_code = validate.get_str(body, "snowcat_unit_code", max_len=24)
    window_start = validate.get_dt(body, "window_start")
    window_end = validate.get_dt(body, "window_end")
    winch_required = validate.get_bool(body, "winch_required", required=False,
                                       default=False)
    anchor = validate.get_str(body, "winch_anchor_code", required=False,
                              max_len=64)
    # Priority 6.
    if window_start >= window_end:
        raise ApiError("ERR_WINDOW_INVALID")
    # Priority 8.
    if winch_required and not anchor:
        raise ApiError("ERR_WINCH_ANCHOR_REQUIRED")
    # Priority 10: sequence_index per cat route within the season.
    season = db.store.seasons.get(area["season_id"])
    for peer in db.season_tasks(area["season_id"]):
        if (peer["cat_route_code"] == route_code
                and peer["sequence_index"] == sequence_index):
            raise ApiError("ERR_DUPLICATE_CODE")
    # Priority 11.
    cascade.require_season_writable(season)
    row = db.new_row({
        "terrain_area_id": area["id"],
        "cat_route_code": route_code,
        "sequence_index": sequence_index,
        "snowcat_unit_code": unit_code,
        "winch_required": winch_required,
        "winch_anchor_code": anchor,
        "window_start": window_start,
        "window_end": window_end,
        "state": "PLANNED",
        "passes_completed": 0,
        "coverage_pct": 0.0,
        "dispatched_at": None,
        "completed_at": None,
    })
    db.store.tasks[row["id"]] = row
    return response.object_response(serialize.grooming_task(row), 201)


@bp.route("/grooming-tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    auth(*ALL_ROLES)
    row = validate.path_row(db.store.tasks, task_id, "ERR_GROOMING_TASK_NOT_FOUND")
    return response.object_response(serialize.grooming_task(row), 200)


@bp.route("/grooming-tasks", methods=["GET"])
def list_tasks():
    auth(*ALL_ROLES)
    limit, offset = validate.pagination()
    rows = db.ordered(db.store.tasks)
    area_id = validate.query_value("terrain_area_id")
    route_code = validate.query_value("cat_route_code")
    unit_code = validate.query_value("snowcat_unit_code")
    state = validate.query_value("state")
    if area_id:
        rows = [r for r in rows if r["terrain_area_id"] == area_id]
    if route_code:
        rows = [r for r in rows if r["cat_route_code"] == route_code]
    if unit_code:
        rows = [r for r in rows if r["snowcat_unit_code"] == unit_code]
    if state:
        rows = [r for r in rows if r["state"] == state]
    return response.list_response(rows, serialize.grooming_task, limit, offset)


@bp.route("/grooming-tasks/<task_id>/dispatch", methods=["POST"])
def dispatch_task(task_id):
    auth(GROOMING_LEAD)
    task = validate.path_row(db.store.tasks, task_id, "ERR_GROOMING_TASK_NOT_FOUND")
    area = db.store.areas.get(task["terrain_area_id"])
    season = db.store.seasons.get(area["season_id"]) if area else None
    # Priority 11: grooming is expressly permitted in PRESEASON.
    cascade.require_season_writable(season)
    # Priority 12.
    if area["opening_state"] in BLOCKED_TERRAIN:
        raise ApiError("ERR_TERRAIN_STATE_INVALID")
    # Priority 15.
    if task["state"] not in DISPATCHABLE:
        raise ApiError("ERR_WORKFLOW_STATE_INVALID")
    # Priority 40 before priority 41.
    for peer in db.season_tasks(area["season_id"]):
        if peer["id"] == task["id"]:
            continue
        if peer["cat_route_code"] != task["cat_route_code"]:
            continue
        if peer["sequence_index"] < task["sequence_index"] and peer["state"] in UNFINISHED:
            raise ApiError("ERR_GROOM_SEQUENCE_VIOLATION")
    for peer in db.ordered(db.store.tasks):
        if peer["id"] == task["id"] or peer["state"] != "DISPATCHED":
            continue
        if peer["snowcat_unit_code"] != task["snowcat_unit_code"]:
            continue
        if (peer["window_start"] < task["window_end"]
                and peer["window_end"] > task["window_start"]):
            raise ApiError("ERR_SNOWCAT_CONFLICT")
    task["state"] = "DISPATCHED"
    task["dispatched_at"] = db.now()
    db.mark(task)
    if area["opening_state"] == "CLOSED":
        area["opening_state"] = "PREP"
        db.mark(area)
    return response.object_response(serialize.grooming_task(task), 200)


@bp.route("/grooming-tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id):
    auth(GROOMING_LEAD)
    task = validate.path_row(db.store.tasks, task_id, "ERR_GROOMING_TASK_NOT_FOUND")
    body = validate.body()
    passes = validate.get_int(body, "passes_completed", minimum=1)
    area = db.store.areas.get(task["terrain_area_id"])
    season = db.store.seasons.get(area["season_id"]) if area else None
    cascade.require_season_writable(season)
    # Priority 15.
    if task["state"] != "DISPATCHED":
        raise ApiError("ERR_WORKFLOW_STATE_INVALID")
    coverage = calc.groom_coverage_pct(passes, area["acres"],
                                      task["winch_required"],
                                      area["terrain_class"])
    task["state"] = "COMPLETED"
    task["completed_at"] = db.now()
    task["passes_completed"] = passes
    task["coverage_pct"] = coverage
    db.mark(task)
    area["groom_coverage_pct"] = coverage
    area["last_groomed_at"] = db.now()
    db.mark(area)
    cascade.reevaluate_readiness(area)
    return response.object_response(serialize.grooming_task(task), 200)
