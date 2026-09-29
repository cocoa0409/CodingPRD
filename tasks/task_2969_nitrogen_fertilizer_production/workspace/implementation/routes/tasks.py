"""Outage work steps and the dependency forest (PRD 3.9)."""
from flask import Blueprint, request

import calc
import serialize
import validate as v
from auth import ALL_ROLES, PROCESS_ENGINEER, actor
from envelope import list_response, object_response, paging
from guards import duplicate, filtered, load, state
from mutate import touch
from store import by_seq, db, stamp_new

bp = Blueprint("tasks", __name__)
PREFIX = "/nitrogen-ops/turnaround-tasks"
TASK_STATUSES = ("PENDING", "READY", "DONE", "BLOCKED")


def _closes_cycle(predecessor, turnaround_id):
    """Follow the predecessor chain: it must stay inside the outage and terminate."""
    seen = set()
    node = predecessor
    while node is not None:
        if node["turnaround_id"] != turnaround_id or node["id"] in seen:
            return True
        seen.add(node["id"])
        node = db.tasks.get(node["predecessor_task_id"]) \
            if node["predecessor_task_id"] else None
    return False


@bp.post(PREFIX)
def create_task():
    actor([PROCESS_ENGINEER])
    body = v.get_body()
    turnaround_id = v.s_id(body, "turnaround_id")
    predecessor_id = v.s_id(body, "predecessor_task_id", required=False)
    task_code = v.s_code(body, "task_code", 2, 16)
    duration = v.s_int(body, "duration_days", ge=1)
    turnaround = load("turnarounds", turnaround_id)
    predecessor = load("tasks", predecessor_id) if predecessor_id is not None else None
    duplicate("tasks", "task_code", task_code,
              scope=("turnaround_id", turnaround_id))
    state(turnaround["status"] in ("DRAFT", "SUBMITTED"))
    if predecessor is not None:
        state(not _closes_cycle(predecessor, turnaround_id), "ERR_TASK_CYCLE_DETECTED")
    row = {
        "turnaround_id": turnaround_id,
        "predecessor_task_id": predecessor_id,
        "task_code": task_code,
        "duration_days": duration,
        "status": "PENDING",
    }
    stamp_new(row)
    db.tasks[row["id"]] = row
    touch(turnaround)
    return object_response(serialize.task_json(row), 201)


@bp.get(PREFIX + "/<id>")
def get_task(id):
    actor(ALL_ROLES)
    return object_response(serialize.task_json(load("tasks", id)))


@bp.get(PREFIX)
def list_tasks():
    actor(ALL_ROLES)
    limit, offset = paging(request.args)
    rows = filtered("tasks", [
        ("turnaround_id", v.query_str("turnaround_id")),
        ("predecessor_task_id", v.query_str("predecessor_task_id")),
        ("status", v.query_enum("status", TASK_STATUSES)),
    ])
    return list_response(serialize.dump("tasks", rows), limit, offset)


@bp.post(PREFIX + "/<id>/complete")
def complete_task(id):
    actor([PROCESS_ENGINEER])
    v.get_body()
    task = load("tasks", id)
    state(task["status"] not in ("DONE", "BLOCKED"))
    turnaround = db.turnarounds[task["turnaround_id"]]
    state(turnaround["status"] == "IN_PROGRESS")
    predecessor = db.tasks.get(task["predecessor_task_id"]) \
        if task["predecessor_task_id"] else None
    state(predecessor is None or predecessor["status"] == "DONE",
          "ERR_TASK_PREDECESSOR_NOT_DONE")
    # A still-PENDING step inside an in-progress outage surfaces here too (PRD 2.11).
    state(task["status"] == "READY", "ERR_TASK_PREDECESSOR_NOT_DONE")
    task["status"] = "DONE"
    touch(task)
    touch(turnaround)
    for successor in by_seq([t for t in db.tasks.values()
                             if t["predecessor_task_id"] == task["id"]
                             and t["status"] == "PENDING"]):
        successor["status"] = "READY"
        touch(successor)
    return object_response(serialize.task_json(task))
