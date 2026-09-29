"""Disciplinary actions and retraining completion."""

from datetime import timedelta

from flask import Blueprint

import calc
import serializers
from auth import require, DISCIPLINE_READ
from common import driver_actions, filtered, lookup, paginate, retraining_pending
from envelope import ok, created
from errors import fail
from shape import MISSING, f, filters, given, present, read_body
from store import base_row, db, touch

bp = Blueprint("discipline", __name__)

ACTION_SPEC = [
    f("driver_id", "string", required=True),
    f("crash_id", "string", required=True),
    f("action_type", "string", required=True, enum=calc.ACTION_TYPES),
    f("action_note", "string", required=True),
    f("suspension_start_at", "instant"),
    f("suspension_end_at", "instant"),
    f("retraining_course_code", "string"),
    f("override_reason", "string"),
]


@bp.post("/disciplinary-actions")
def issue_action():
    user_id, _role = require("SafetyManager")
    values = read_body(ACTION_SPEC)
    action_type = values["action_type"]
    has_start = present(values, "suspension_start_at")
    has_end = present(values, "suspension_end_at")
    has_course = present(values, "retraining_course_code")
    if action_type == "SUSPENSION":
        if not has_start or not has_end:
            fail("ERR_INVALID_REQUEST",
                 "suspension_start_at and suspension_end_at are required for a "
                 "SUSPENSION")
    else:
        if has_start or has_end:
            fail("ERR_INVALID_REQUEST",
                 "suspension_start_at and suspension_end_at are only permitted "
                 "on a SUSPENSION")
    if action_type in ("RETRAINING", "SUSPENSION"):
        if not has_course:
            fail("ERR_INVALID_REQUEST",
                 "retraining_course_code is required for a %s" % action_type)
    else:
        if has_course:
            fail("ERR_INVALID_REQUEST",
                 "retraining_course_code is only permitted on a RETRAINING or a "
                 "SUSPENSION")
    start = given(values, "suspension_start_at")
    end = given(values, "suspension_end_at")
    if start is not None and end is not None and end <= start:
        fail("ERR_INVALID_REQUEST",
             "suspension_end_at must be later than suspension_start_at")
    driver = lookup("drivers", values["driver_id"])
    crash = lookup("crashes", values["crash_id"])
    if driver["status"] == "TERMINATED":
        fail("ERR_DRIVER_STATE_INVALID",
             "A terminated driver accepts no further disciplinary action")
    if action_type == "SUSPENSION":
        buffer_delta = timedelta(hours=calc.SUSPENSION_BUFFER_HOURS)
        for existing in driver_actions(driver["id"]):
            if existing["action_type"] != "SUSPENSION":
                continue
            if existing["status"] == "VOIDED":
                continue
            ex_start = existing["suspension_start_at"] - buffer_delta
            ex_end = existing["suspension_end_at"] + buffer_delta
            if start < ex_end and ex_start < end:
                fail("ERR_SUSPENSION_WINDOW_CONFLICT",
                     "The suspension window conflicts with an existing "
                     "suspension of this driver")
    if crash["driver_id"] != driver["id"]:
        fail("ERR_DRIVER_CRASH_MISMATCH",
             "The supplied driver_id is not the driver recorded on that crash")
    if crash["preventability_status"] != "PREVENTABLE":
        fail("ERR_CRASH_NOT_PREVENTABLE",
             "Discipline may only arise from a PREVENTABLE crash")
    tier = calc.required_action_tier(driver)
    if calc.ACTION_TYPE_RANK[action_type] < calc.TIER_RANK[tier]:
        fail("ERR_ACTION_TIER_INSUFFICIENT",
             "A %s is lighter than the driver's required tier of %s"
             % (action_type, tier))
    override_reason = given(values, "override_reason")
    if action_type == "SUSPENSION":
        if (calc.staffing_posture(driver["terminal_id"]) == "CRITICAL"
                and override_reason is None):
            fail("ERR_STAFFING_OVERRIDE_REQUIRED",
                 "The terminal's staffing posture is CRITICAL; an override_reason "
                 "is required")
    row = base_row()
    row["driver_id"] = driver["id"]
    row["crash_id"] = crash["id"]
    row["action_type"] = action_type
    row["action_note"] = values["action_note"]
    row["suspension_start_at"] = start
    row["suspension_end_at"] = end
    row["retraining_course_code"] = given(values, "retraining_course_code")
    row["retraining_status"] = "PENDING" if has_course else "NOT_REQUIRED"
    row["status"] = "ISSUED"
    row["override_reason"] = override_reason
    row["override_flag"] = override_reason is not None
    row["issued_by_user_id"] = user_id
    row["completed_at"] = None
    db.disciplinary_actions[row["id"]] = row
    if action_type == "RETRAINING" and driver["status"] == "ACTIVE":
        driver["status"] = "RETRAINING_REQUIRED"
    elif action_type == "SUSPENSION" and driver["status"] == "ACTIVE":
        driver["status"] = "SUSPENDED_PENDING_ACTION"
    touch(driver)
    return created(serializers.disciplinary_action(row))


@bp.get("/disciplinary-actions/<entity_id>")
def read_action(entity_id):
    require(*DISCIPLINE_READ)
    return ok(serializers.disciplinary_action(
        lookup("disciplinary_actions", entity_id)))


@bp.get("/disciplinary-actions")
def list_actions():
    require(*DISCIPLINE_READ)
    criteria = filters({
        "driver_id": None,
        "crash_id": None,
        "status": calc.ACTION_STATUSES,
        "action_type": calc.ACTION_TYPES,
        "retraining_status": calc.RETRAINING_STATUSES,
    })
    return paginate(filtered("disciplinary_actions", criteria),
                    serializers.disciplinary_action)


@bp.post("/disciplinary-actions/<entity_id>/complete-retraining")
def complete_retraining(entity_id):
    require("SafetyAdmin")
    read_body([f("completion_note", "string")])
    action = lookup("disciplinary_actions", entity_id)
    if action["status"] != "ISSUED" or action["retraining_status"] != "PENDING":
        fail("ERR_DISCIPLINARY_ACTION_STATE_INVALID",
             "This action has no outstanding retraining to complete")
    if action["action_type"] == "SUSPENSION":
        if db.now <= action["suspension_end_at"]:
            fail("ERR_SUSPENSION_NOT_ELAPSED",
                 "The out-of-service period has not yet elapsed")
    action["status"] = "COMPLETED"
    action["retraining_status"] = "COMPLETED"
    action["completed_at"] = db.now
    touch(action)
    driver = db.drivers[action["driver_id"]]
    if (not retraining_pending(driver["id"], exclude_id=action["id"])
            and driver["status"] in ("RETRAINING_REQUIRED",
                                     "SUSPENDED_PENDING_ACTION")):
        driver["status"] = "ACTIVE"
        touch(driver)
    return ok(serializers.disciplinary_action(action))
