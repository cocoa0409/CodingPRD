"""Sequencing the trades: crew capacity, material readiness and delay propagation."""
from flask import Blueprint

from errors import AppError
from store import db, base_row, now, bump, ordered
from util import (
    authorize, check_staff_identity, parse_body, ok, ok_list, paginate, qfilter,
    req_str, opt_id, req_enum, req_dt, opt_int, opt_bool, add_days,
)
from routes.common import fetch, own_subcontractor
from services.constants import ACTIVE_TASK_STATUSES, JOBSITE_CURE_BUFFER_DAYS
from services.calc import delay_days_for, float_days_for

bp = Blueprint("schedule", __name__)

TASK_READ_ROLES = ["PlatformAdmin", "ProjectManager", "Estimator", "Controller",
                   "Client", "Subcontractor"]
PROGRESS_ACTIONS = ("START", "COMPLETE")


@bp.post("/schedule-tasks")
def create_schedule_task():
    user_id, role = authorize(["ProjectManager"])
    body = parse_body()
    project_id = req_str(body, "project_id")
    subcontractor_id = req_str(body, "subcontractor_id")
    task_name = req_str(body, "task_name")
    planned_start = req_dt(body, "planned_start")
    planned_finish = req_dt(body, "planned_finish")
    predecessor_task_id = opt_id(body, "predecessor_task_id")
    driving_allowance_item_id = opt_id(body, "driving_allowance_item_id")
    lag_days = opt_int(body, "lag_days", 0, minimum=0)
    exclusive_use = opt_bool(body, "exclusive_use", False)

    if planned_finish <= planned_start:
        raise AppError("ERR_INVALID_REQUEST",
                       "planned_finish must be strictly later than planned_start.")

    # ladder step 6
    project = db.projects.get(project_id)
    if project is None:
        raise AppError("ERR_PROJECT_NOT_FOUND")
    subcontractor = db.subcontractors.get(subcontractor_id)
    if subcontractor is None:
        raise AppError("ERR_SUBCONTRACTOR_NOT_FOUND")
    predecessor = None
    if predecessor_task_id is not None:
        predecessor = db.schedule_tasks.get(predecessor_task_id)
        if predecessor is None:
            raise AppError("ERR_SCHEDULE_TASK_NOT_FOUND")
    driving_item = None
    if driving_allowance_item_id is not None:
        driving_item = db.allowance_items.get(driving_allowance_item_id)
        if driving_item is None:
            raise AppError("ERR_ALLOWANCE_ITEM_NOT_FOUND")

    check_staff_identity(user_id, role)

    # ladder step 21
    if predecessor is not None and predecessor["project_id"] != project_id:
        raise AppError("ERR_PREDECESSOR_CROSS_PROJECT")
    # ladder step 22
    if driving_item is not None and driving_item["project_id"] != project_id:
        raise AppError("ERR_ALLOWANCE_PROJECT_MISMATCH")

    # ladder step 26 - crew capacity, HALF-OPEN intervals; touching does not intersect
    overlapping = 0
    for task in db.schedule_tasks.values():
        if task["subcontractor_id"] != subcontractor_id:
            continue
        if task["status"] not in ACTIVE_TASK_STATUSES:
            continue
        if task["planned_start"] < planned_finish and planned_start < task["planned_finish"]:
            overlapping += 1
    if overlapping >= subcontractor["crew_capacity"]:
        raise AppError("ERR_CREW_CAPACITY_CONFLICT")

    # ladder step 27 - jobsite exclusive use, CLOSED buffered intervals; touching intersects
    if exclusive_use:
        new_end = add_days(planned_finish, JOBSITE_CURE_BUFFER_DAYS)
        for task in db.schedule_tasks.values():
            if task["project_id"] != project_id or not task.get("exclusive_use"):
                continue
            if task["status"] not in ACTIVE_TASK_STATUSES:
                continue
            other_end = add_days(task["planned_finish"], JOBSITE_CURE_BUFFER_DAYS)
            if task["planned_start"] <= new_end and planned_start <= other_end:
                raise AppError("ERR_JOBSITE_EXCLUSIVE_CONFLICT")

    row = base_row()
    row.update({
        "project_id": project_id,
        "subcontractor_id": subcontractor_id,
        "predecessor_task_id": predecessor_task_id,
        "driving_allowance_item_id": driving_allowance_item_id,
        "task_name": task_name,
        "planned_start": planned_start,
        "planned_finish": planned_finish,
        "lag_days": lag_days,
        "exclusive_use": exclusive_use,
        "status": "PLANNED",
        "material_ready_at": None,
        "actual_start": None,
        "actual_finish": None,
        "delay_days": 0,
        "float_days": None,
        "released_at": None,
    })
    db.schedule_tasks[row["id"]] = row
    return ok(row, 201)


@bp.get("/schedule-tasks/<task_id>")
def get_schedule_task(task_id):
    user_id, role = authorize(TASK_READ_ROLES)
    task = fetch("schedule_tasks", task_id)
    check_staff_identity(user_id, role)
    return ok(task, 200)


@bp.get("/schedule-tasks")
def list_schedule_tasks():
    user_id, role = authorize(TASK_READ_ROLES)
    check_staff_identity(user_id, role)
    rows = ordered(db.schedule_tasks.values())
    for name in ("project_id", "subcontractor_id", "predecessor_task_id",
                 "driving_allowance_item_id", "status"):
        value = qfilter(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.post("/schedule-tasks/<task_id>/release")
def release_schedule_task(task_id):
    user_id, role = authorize(["ProjectManager"])
    task = fetch("schedule_tasks", task_id)
    parse_body()
    check_staff_identity(user_id, role)

    # ladder step 10
    if task["status"] != "PLANNED":
        raise AppError("ERR_TASK_INVALID_STATE")
    # ladder step 11
    project = db.projects.get(task["project_id"])
    if project is None or project["status"] != "UNDER_CONSTRUCTION":
        raise AppError("ERR_PROJECT_NOT_UNDER_CONSTRUCTION")

    # ladder step 24 - the three release gates, in order
    if task.get("driving_allowance_item_id") is not None:
        item = db.allowance_items.get(task["driving_allowance_item_id"])
        if item is None or item["status"] not in ("LOCKED", "RECONCILED"):
            raise AppError("ERR_ALLOWANCE_NOT_LOCKED")
    if task.get("material_ready_at") is not None:
        if task["material_ready_at"] > task["planned_start"]:
            raise AppError("ERR_MATERIAL_NOT_READY")
    predecessor = None
    if task.get("predecessor_task_id") is not None:
        predecessor = db.schedule_tasks.get(task["predecessor_task_id"])
        if predecessor is None or predecessor["status"] != "COMPLETE":
            raise AppError("ERR_PREDECESSOR_INCOMPLETE")

    task["status"] = "RELEASED"
    task["released_at"] = now()
    if predecessor is not None:
        task["float_days"] = float_days_for(task, predecessor)
    bump(task)
    return ok(task, 200)


@bp.post("/schedule-tasks/<task_id>/progress")
def progress_schedule_task(task_id):
    user_id, role = authorize(["Subcontractor"])
    task = fetch("schedule_tasks", task_id)
    body = parse_body()
    action = req_enum(body, "action", PROGRESS_ACTIONS)

    # ladder step 8
    own_subcontractor(task["subcontractor_id"], user_id, role)

    if action == "START":
        # ladder step 10
        if task["status"] != "RELEASED":
            raise AppError("ERR_TASK_INVALID_STATE")
        if task.get("material_ready_at") is not None and now() < task["material_ready_at"]:
            raise AppError("ERR_MATERIAL_NOT_READY")
        task["status"] = "IN_PROGRESS"
        task["actual_start"] = now()
        bump(task)
        return ok(task, 200)

    # COMPLETE
    if task["status"] != "IN_PROGRESS":
        raise AppError("ERR_TASK_INVALID_STATE")

    task["status"] = "COMPLETE"
    task["actual_finish"] = now()
    task["delay_days"] = delay_days_for(task)
    bump(task)

    if task["delay_days"] > 0:
        successors = [t for t in db.schedule_tasks.values()
                      if t.get("predecessor_task_id") == task["id"]
                      and t["status"] in ("PLANNED", "RELEASED")]
        successors.sort(key=lambda t: (t["planned_start"], t["created_at"], t["_seq"]))
        for successor in successors:
            successor["planned_start"] = add_days(successor["planned_start"],
                                                  task["delay_days"])
            successor["planned_finish"] = add_days(successor["planned_finish"],
                                                   task["delay_days"])
            successor["float_days"] = float_days_for(successor, task)
            bump(successor)

    return ok(task, 200)
