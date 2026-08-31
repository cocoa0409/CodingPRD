"""Rigging gear, inspections and gear assignments."""
from datetime import timedelta

from flask import Blueprint

import calc
import cascades
import derive
from core import fail, fmt_dt, new_record, ordered, parse_dt, respond_list, respond_object, \
    store, touch
from guards import (Body, auth, body, fk, must_exist, pagination, paginate, q_enum, q_str)

bp = Blueprint("gear", __name__)

GEAR_TYPES = ["SLING", "SHACKLE", "SPREADER_BAR"]
GEAR_STATUSES = ["DUE_INSPECTION", "SERVICEABLE", "QUARANTINED", "RETIRED"]
INSPECTION_RESULTS = ["PASS", "FAIL", "REPAIR_PASS", "RETIRE"]
ASSIGNMENT_STATUSES = ["ACTIVE", "RELEASED", "VOIDED"]


# ------------------------------------------------------------ rigging gear ---
@bp.post("/rigging-gear")
def create_gear():
    auth(["SafetyManager"])
    b = Body(body())
    gear_tag = b.string("gear_tag")
    gear_type = b.enum("gear_type", GEAR_TYPES)
    rated_wll_lb = b.integer("rated_wll_lb", exclusive_min=0)
    weight_lb = b.integer("weight_lb", minimum=0)
    interval = b.integer("inspection_interval_days", required=False, default=30, exclusive_min=0)
    for g in store.rigging_gear.values():
        if g["gear_tag"] == gear_tag:
            fail("ERR_DUPLICATE_GEAR_TAG", "That gear tag is already registered.")
    rec = new_record({
        "gear_tag": gear_tag,
        "gear_type": gear_type,
        "rated_wll_lb": rated_wll_lb,
        "weight_lb": weight_lb,
        "inspection_interval_days": interval,
        "last_inspection_at": None,
        "next_inspection_due_at": None,
        "repair_count": 0,
        "effective_wll_lb": rated_wll_lb,
        "status": "DUE_INSPECTION",
    })
    store.rigging_gear[rec["id"]] = rec
    return respond_object(derive.gear_json(rec), 201)


@bp.get("/rigging-gear/<gid>")
def read_gear(gid):
    auth(["Dispatcher", "LiftDirector", "Engineer", "Operator", "SafetyManager"])
    rec = must_exist("rigging_gear", gid)
    return respond_object(derive.gear_json(rec))


@bp.get("/rigging-gear")
def list_gear():
    auth(["Dispatcher", "LiftDirector", "Engineer", "SafetyManager"])
    limit, offset = pagination()
    status = q_enum("status", GEAR_STATUSES)
    gear_type = q_enum("gear_type", GEAR_TYPES)
    rows = ordered(store.rigging_gear)
    if status:
        rows = [r for r in rows if derive.gear_status(r) == status]
    if gear_type:
        rows = [r for r in rows if r["gear_type"] == gear_type]
    items, limit, offset, total = paginate(rows, limit, offset, derive.gear_json)
    return respond_list(items, limit, offset, total)


@bp.post("/rigging-gear/<gid>/retire")
def retire_gear(gid):
    auth(["SafetyManager"])
    rec = must_exist("rigging_gear", gid)
    b = Body(body())
    b.string("reason")
    if derive.gear_status(rec) == "RETIRED":
        fail("ERR_INVALID_GEAR_STATE", "The gear item is already retired.")
    rec["status"] = "RETIRED"
    touch(rec)
    cascades.gear_left_serviceable(rec)
    return respond_object(derive.gear_json(rec))


# -------------------------------------------------------------- inspections --
@bp.post("/gear-inspections")
def create_inspection():
    auth(["SafetyManager"])
    b = Body(body())
    gear_id = b.string("gear_id")
    result = b.enum("result", INSPECTION_RESULTS)
    inspector_note = b.string("inspector_note", allow_empty=True)
    gear = fk("rigging_gear", gear_id)
    if derive.gear_status(gear) == "RETIRED":
        fail("ERR_INVALID_GEAR_STATE", "A retired gear item cannot be inspected.")

    gear["last_inspection_at"] = store.now_iso()
    if result in ("PASS", "REPAIR_PASS"):
        if result == "REPAIR_PASS":
            gear["repair_count"] += 1
            gear["effective_wll_lb"] = derive.gear_effective_wll(gear)
        gear["status"] = "SERVICEABLE"
        due = store.now + timedelta(days=gear["inspection_interval_days"])
        gear["next_inspection_due_at"] = fmt_dt(due)
        resulting_status = "SERVICEABLE"
    elif result == "FAIL":
        gear["status"] = "QUARANTINED"
        resulting_status = "QUARANTINED"
    else:
        gear["status"] = "RETIRED"
        resulting_status = "RETIRED"
    touch(gear)

    rec = new_record({
        "gear_id": gear_id,
        "result": result,
        "inspector_note": inspector_note,
        "inspected_at": store.now_iso(),
        "resulting_status": resulting_status,
        "repair_count_after": gear["repair_count"],
    }, common=False)
    store.gear_inspections[rec["id"]] = rec

    if result in ("FAIL", "RETIRE"):
        cascades.gear_left_serviceable(gear)
    return respond_object(derive.inspection_json(rec), 201)


@bp.get("/rigging-gear/<gid>/inspections")
def list_inspections(gid):
    auth(["Dispatcher", "LiftDirector", "Engineer", "SafetyManager"])
    must_exist("rigging_gear", gid)
    limit, offset = pagination()
    result = q_enum("result", INSPECTION_RESULTS)
    rows = [r for r in ordered(store.gear_inspections) if r["gear_id"] == gid]
    if result:
        rows = [r for r in rows if r["result"] == result]
    rows = list(reversed(rows))          # newest first
    items, limit, offset, total = paginate(rows, limit, offset, derive.inspection_json)
    return respond_list(items, limit, offset, total)


# --------------------------------------------------------- gear assignments --
@bp.post("/gear-assignments")
def create_assignment():
    auth(["Dispatcher"])
    b = Body(body())
    lift_plan_id = b.string("lift_plan_id")
    gear_id = b.string("gear_id")
    leg_count = b.integer("leg_count", minimum=1, maximum=4)
    sling_angle_deg = b.integer("sling_angle_deg", choices=[30, 45, 60, 90])
    expected_gear_version = b.integer("expected_gear_version")
    plan = fk("lift_plans", lift_plan_id)
    gear = fk("rigging_gear", gear_id)

    if expected_gear_version != gear["version"]:
        fail("ERR_STALE_GEAR_VERSION", "expected_gear_version does not match the gear's version.")
    if derive.gear_status(gear) != "SERVICEABLE":
        fail("ERR_GEAR_NOT_SERVICEABLE", "Only serviceable gear may be committed to a plan.")
    for a in store.gear_assignments.values():
        if (a["lift_plan_id"] == lift_plan_id and a["gear_id"] == gear_id
                and a["status"] == "ACTIVE"):
            fail("ERR_DUPLICATE_GEAR_ASSIGNMENT",
                 "That gear item is already committed to this plan.")

    rec = new_record({
        "lift_plan_id": lift_plan_id,
        "gear_id": gear_id,
        "leg_count": leg_count,
        "sling_angle_deg": sling_angle_deg,
        "load_angle_factor": float(calc.LOAD_ANGLE_FACTORS[sling_angle_deg]),
        "leg_tension_lb": 0,
        "effective_wll_lb": gear["effective_wll_lb"],
        "status": "ACTIVE",
    })
    store.gear_assignments[rec["id"]] = rec
    touch(gear)
    return respond_object(derive.assignment_json(rec), 201)


@bp.get("/gear-assignments/<aid>")
def read_assignment(aid):
    auth(["Dispatcher", "LiftDirector", "Engineer", "SafetyManager"])
    rec = must_exist("gear_assignments", aid)
    return respond_object(derive.assignment_json(rec))


@bp.get("/gear-assignments")
def list_assignments():
    auth(["Dispatcher", "LiftDirector", "Engineer", "SafetyManager"])
    limit, offset = pagination()
    lift_plan_id = q_str("lift_plan_id")
    gear_id = q_str("gear_id")
    status = q_enum("status", ASSIGNMENT_STATUSES)
    rows = ordered(store.gear_assignments)
    if lift_plan_id:
        rows = [r for r in rows if r["lift_plan_id"] == lift_plan_id]
    if gear_id:
        rows = [r for r in rows if r["gear_id"] == gear_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    items, limit, offset, total = paginate(rows, limit, offset, derive.assignment_json)
    return respond_list(items, limit, offset, total)


@bp.post("/gear-assignments/<aid>/release")
def release_assignment(aid):
    auth(["Dispatcher"])
    rec = must_exist("gear_assignments", aid)
    if rec["status"] != "ACTIVE":
        fail("ERR_INVALID_GEAR_STATE", "Only an ACTIVE assignment may be withdrawn.")
    rec["status"] = "RELEASED"
    touch(rec)
    return respond_object(derive.assignment_json(rec))
