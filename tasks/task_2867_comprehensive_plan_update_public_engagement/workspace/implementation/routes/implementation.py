"""Implementation program and monitoring indicators (PRD 3.9)."""
from flask import Blueprint

import constants as K
import serial
import validation as V
from db import bump, clock_now, db, new_row, sort_rows
from errors import ApiError
from response import (authenticate, created, filter_param, ok, paginate,
                      pagination)
from services import calc, planservice, repo

bp = Blueprint("implementation", __name__)

_READERS = K.ALL_ROLES


@bp.post("/planning/implementation-actions")
def create_action():
    authenticate([K.ROLE_STAFF])
    data = V.body()
    plan_id = V.get_str(data, "plan_update_id", 1, None)
    element_id = V.get_str(data, "source_element_id", 1, None)
    action_type = V.get_enum(data, "action_type", K.ACTION_TYPES)
    title = V.get_str(data, "title", 1, 160)
    indicator_name = V.get_str(data, "indicator_name", 1, 80)
    direction = V.get_enum(data, "indicator_direction", K.INDICATOR_DIRECTIONS)
    baseline = V.get_raw_num(data, "baseline_value")
    target = V.get_raw_num(data, "target_value")

    plan = repo.plan(plan_id)
    element = repo.element(element_id)
    planservice.ensure_not_adopted(plan)
    if element["plan_update_id"] != plan["id"]:
        raise ApiError("ERR_CROSS_PLAN_ACTION")

    row = new_row({
        "plan_update_id": plan["id"],
        "source_element_id": element["id"],
        "action_type": action_type,
        "title": title,
        "indicator_name": indicator_name,
        "indicator_direction": direction,
        "baseline_value": baseline,
        "target_value": target,
        "latest_reading_value": None,
        "latest_reading_at": None,
        "reading_count": 0,
        "on_track": False,
        "status": "PENDING",
        "due_at": None,
    })
    db.implementation_actions[row["id"]] = row
    return created(serial.action(row))


@bp.get("/planning/implementation-actions/<row_id>")
def read_action(row_id):
    authenticate(_READERS)
    return ok(serial.action(repo.action(row_id)))


@bp.get("/planning/implementation-actions")
def list_actions():
    authenticate(_READERS)
    limit, offset = pagination()
    plan_id = filter_param("plan_update_id")
    element_id = filter_param("source_element_id")
    status = filter_param("status")
    action_type = filter_param("action_type")
    rows = sort_rows(list(db.implementation_actions.values()))
    if plan_id is not None:
        rows = [r for r in rows if r["plan_update_id"] == plan_id]
    if element_id is not None:
        rows = [r for r in rows if r["source_element_id"] == element_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if action_type is not None:
        rows = [r for r in rows if r["action_type"] == action_type]
    return paginate(rows, limit, offset, serial.action)


@bp.post("/planning/implementation-actions/<row_id>/record-reading")
def record_reading(row_id):
    authenticate([K.ROLE_STAFF])
    row = repo.action(row_id)
    data = V.body()
    reading_value = V.get_raw_num(data, "reading_value")
    if row["status"] == "COMPLETED":
        raise ApiError("ERR_ACTION_ALREADY_COMPLETED")

    row["latest_reading_value"] = reading_value
    row["latest_reading_at"] = clock_now()
    row["reading_count"] = int(row["reading_count"]) + 1
    row["on_track"] = calc.indicator_on_track(row["indicator_direction"],
                                              reading_value,
                                              row["target_value"])
    bump(row)
    plan = db.plan_updates.get(row["plan_update_id"])
    if plan is not None:
        # Only the derived counter moves; the plan's version does not.
        planservice.recompute_counters(plan)
    return ok(serial.action(row))


@bp.post("/planning/implementation-actions/<row_id>/complete")
def complete_action(row_id):
    authenticate([K.ROLE_STAFF])
    row = repo.action(row_id)
    plan = repo.plan(row["plan_update_id"])
    if row["status"] == "PENDING":
        raise ApiError("ERR_ACTION_NOT_SCHEDULED")
    if row["status"] == "COMPLETED":
        raise ApiError("ERR_ACTION_ALREADY_COMPLETED")
    if int(row["reading_count"]) < 1:
        raise ApiError("ERR_NO_INDICATOR_READING")
    if not row["on_track"]:
        raise ApiError("ERR_INDICATOR_OFF_TRACK")

    row["status"] = "COMPLETED"
    bump(row)
    bump(plan)
    return ok(serial.action(row))
