"""Work orders (execution and payroll axes) and irrigation events."""

from flask import Blueprint

import calc
import derive
import service
import store
from common import ApiError, invalid, r2, respond_list, respond_object
from validate import F, auth, pagination, parse_payload

bp = Blueprint("work", __name__)

TASK_TYPES = ("PRUNING", "SUCKERING", "LEAFING", "HARVEST")
EXECUTION_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
PAYROLL_STATUSES = ("NOT_PAYABLE", "PENDING", "APPROVED", "PAID")
OPERATOR_CANCEL_REASONS = ("WEATHER", "CLIENT_REQUEST", "CREW_UNAVAILABLE")
PAYROLL_ACTIONS = ("APPROVE", "PAY")

WORK_ORDER_ROLES = ["VineyardManager", "Controller", "CrewSupervisor"]

WORK_ORDER_SCHEMA = [
    F("block_id", "id", min_len=1),
    F("farming_plan_id", "id", min_len=1),
    F("crew_id", "id", min_len=1),
    F("task_type", "enum", values=TASK_TYPES),
    F("scheduled_start", "datetime"),
    F("scheduled_end", "datetime"),
    F("planned_vines", "integer", ge=0),
    F("planned_hours", "number", gt=0),
]


@bp.route("/work-orders", methods=["POST"])
def create_work_order():
    auth(["VineyardManager"])
    body = parse_payload(WORK_ORDER_SCHEMA)
    start = body["_dt_scheduled_start"]
    end = body["_dt_scheduled_end"]
    if not end > start:
        raise invalid("scheduled_end must be strictly later than scheduled_start.")

    block = service.get_block(body["block_id"])
    plan = service.get_plan(body["farming_plan_id"])
    crew = service.get_crew(body["crew_id"])

    service.require_plan_approved(plan)
    service.require_block_live(block)
    service.require_crew_active(crew)

    # rung 17 — an uncertified crew may not be booked inside an open re-entry window
    rei_clear_at = derive.block_clearances(block)[0]
    if rei_clear_at is not None and start < rei_clear_at and not crew["pest_certified"]:
        raise ApiError("ERR_CREW_NOT_PEST_CERTIFIED", 409)

    # rung 18
    if service.crew_conflicts(crew["id"], block["id"], start, end):
        raise ApiError("ERR_CREW_SCHEDULE_CONFLICT", 409)

    # rung 19
    if plan["block_id"] != block["id"]:
        raise ApiError("ERR_PLAN_BLOCK_MISMATCH", 409)
    if body["task_type"] not in crew["task_capabilities"]:
        raise ApiError("ERR_CREW_TASK_MISMATCH", 409)

    estimated = calc.labor_cost(crew, body["planned_vines"], body["planned_hours"])

    # rung 20
    committed = derive.plan_committed_cost(plan["id"])
    if r2(committed + estimated) > plan["total_budget"]:
        raise ApiError("ERR_PLAN_BUDGET_EXCEEDED", 409)

    row = store.new_row()
    row.update({
        "block_id": block["id"],
        "farming_plan_id": plan["id"],
        "crew_id": crew["id"],
        "task_type": body["task_type"],
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "_start": start,
        "_end": end,
        "planned_vines": body["planned_vines"],
        "planned_hours": body["planned_hours"],
        "actual_vines": None,
        "actual_hours": None,
        "execution_status": "SCHEDULED",
        "payroll_status": "NOT_PAYABLE",
        "estimated_labor_cost": estimated,
        "actual_labor_cost": None,
        "cancel_reason": None,
        "started_at": None,
        "completed_at": None,
    })
    store.work_orders[row["id"]] = row
    return respond_object(derive.serialize_work_order(row), 201)


@bp.route("/work-orders/<order_id>", methods=["GET"])
def read_work_order(order_id):
    auth(WORK_ORDER_ROLES)
    order = service.get_work_order(order_id)
    return respond_object(derive.serialize_work_order(order))


@bp.route("/work-orders", methods=["GET"])
def list_work_orders():
    auth(WORK_ORDER_ROLES)
    rows = service.filtered(store.work_orders, (
        ("block_id", "block_id"),
        ("crew_id", "crew_id"),
        ("farming_plan_id", "farming_plan_id"),
        ("execution_status", "execution_status"),
        ("payroll_status", "payroll_status"),
    ))
    items, limit, offset, total = service.page(rows, derive.serialize_work_order)
    return respond_list(items, limit, offset, total)


@bp.route("/work-orders/<order_id>/start", methods=["POST"])
def start_work_order(order_id):
    user_id, role = auth(["CrewSupervisor"])
    parse_payload([])
    order = service.get_work_order(order_id)
    service.require_crew_owner(role, user_id, order["crew_id"])

    if order["execution_status"] != "SCHEDULED":
        raise ApiError("ERR_WORK_ORDER_NOT_SCHEDULED", 409)
    crew = store.crews[order["crew_id"]]
    service.require_crew_active(crew)

    # rung 17 — re-entry clearance at start
    block = store.blocks[order["block_id"]]
    rei_clear_at = derive.block_clearances(block)[0]
    if (rei_clear_at is not None and store.now_utc() < rei_clear_at
            and not crew["pest_certified"]):
        raise ApiError("ERR_REENTRY_INTERVAL_ACTIVE", 409)

    order["execution_status"] = "IN_PROGRESS"
    order["started_at"] = store.now_utc()
    store.touch(order)
    return respond_object(derive.serialize_work_order(order))


COMPLETE_SCHEMA = [
    F("actual_vines", "integer", ge=0),
    F("actual_hours", "number", gt=0),
]


@bp.route("/work-orders/<order_id>/complete", methods=["POST"])
def complete_work_order(order_id):
    user_id, role = auth(["CrewSupervisor"])
    body = parse_payload(COMPLETE_SCHEMA)
    order = service.get_work_order(order_id)
    service.require_crew_owner(role, user_id, order["crew_id"])

    if order["execution_status"] != "IN_PROGRESS":
        raise ApiError("ERR_WORK_ORDER_NOT_IN_PROGRESS", 409)

    crew = store.crews[order["crew_id"]]
    order["actual_vines"] = body["actual_vines"]
    order["actual_hours"] = body["actual_hours"]
    order["actual_labor_cost"] = calc.labor_cost(
        crew, body["actual_vines"], body["actual_hours"])
    order["execution_status"] = "COMPLETED"
    order["payroll_status"] = "PENDING"
    order["completed_at"] = store.now_utc()
    store.touch(order)
    return respond_object(derive.serialize_work_order(order))


CANCEL_SCHEMA = [F("cancel_reason", "enum", values=OPERATOR_CANCEL_REASONS)]


@bp.route("/work-orders/<order_id>/cancel", methods=["POST"])
def cancel_work_order(order_id):
    auth(["VineyardManager"])
    body = parse_payload(CANCEL_SCHEMA)
    order = service.get_work_order(order_id)

    if order["execution_status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_WORK_ORDER_TERMINAL", 409)

    was_in_progress = order["execution_status"] == "IN_PROGRESS"
    order["execution_status"] = "CANCELLED"
    order["cancel_reason"] = body["cancel_reason"]
    if was_in_progress:
        crew = store.crews[order["crew_id"]]
        order["actual_labor_cost"] = calc.cancellation_pay(crew)
        order["payroll_status"] = "PENDING"
    store.touch(order)
    return respond_object(derive.serialize_work_order(order))


PAYROLL_SCHEMA = [
    F("payroll_action", "enum", values=PAYROLL_ACTIONS),
    F("payroll_note", "string", required=False, nullable=True,
      max_len=1000, blank_ok=True),
]


@bp.route("/work-orders/<order_id>/payroll", methods=["POST"])
def payroll_work_order(order_id):
    auth(["Controller"])
    body = parse_payload(PAYROLL_SCHEMA)
    order = service.get_work_order(order_id)

    action = body["payroll_action"]
    if action == "APPROVE":
        if order["payroll_status"] != "PENDING":
            raise ApiError("ERR_PAYROLL_STATE_INVALID", 409)
        order["payroll_status"] = "APPROVED"
    else:
        if order["payroll_status"] != "APPROVED":
            raise ApiError("ERR_PAYROLL_STATE_INVALID", 409)
        order["payroll_status"] = "PAID"
    store.touch(order)
    return respond_object(derive.serialize_work_order(order))


# --------------------------------------------------------------------------
# IrrigationEvent
# --------------------------------------------------------------------------

IRRIGATION_ROLES = ["VineyardManager", "Agronomist", "CrewSupervisor"]

IRRIGATION_SCHEMA = [
    F("block_id", "id", min_len=1),
    F("farming_plan_id", "id", min_len=1),
    F("scheduled_start", "datetime"),
    F("scheduled_end", "datetime"),
    F("et0_inches", "number", ge=0),
    F("crop_coefficient", "number", gt=0),
    F("soil_moisture_pct", "number", ge=0, le=100),
    F("field_capacity_pct", "number", ge=0, le=100),
    F("root_zone_depth_in", "number", gt=0),
    F("effective_rain_inches", "number", ge=0),
    F("water_unit_cost_per_acre_inch", "number", ge=0),
]


@bp.route("/irrigation-events", methods=["POST"])
def create_irrigation():
    auth(["VineyardManager", "Agronomist"])
    body = parse_payload(IRRIGATION_SCHEMA)
    start = body["_dt_scheduled_start"]
    end = body["_dt_scheduled_end"]
    if not end > start:
        raise invalid("scheduled_end must be strictly later than scheduled_start.")

    block = service.get_block(body["block_id"])
    plan = service.get_plan(body["farming_plan_id"])

    service.require_plan_approved(plan)
    service.require_block_live(block)

    if plan["block_id"] != block["id"]:
        raise ApiError("ERR_PLAN_BLOCK_MISMATCH", 409)

    figures = calc.irrigation_figures(
        body, plan["quality_target"], plan["seasonal_water_cap_inches"],
        derive.season_applied_inches(block["id"]))

    row = store.new_row()
    row.update({
        "block_id": block["id"],
        "farming_plan_id": plan["id"],
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "_start": start,
        "_end": end,
        "et0_inches": body["et0_inches"],
        "crop_coefficient": body["crop_coefficient"],
        "soil_moisture_pct": body["soil_moisture_pct"],
        "field_capacity_pct": body["field_capacity_pct"],
        "root_zone_depth_in": body["root_zone_depth_in"],
        "effective_rain_inches": body["effective_rain_inches"],
        "water_unit_cost_per_acre_inch": body["water_unit_cost_per_acre_inch"],
        "irrigation_status": "SCHEDULED",
        "applied_inches": None,
        "water_cost": None,
        "applied_at": None,
    })
    row.update(figures)
    store.irrigation_events[row["id"]] = row
    return respond_object(derive.serialize_irrigation(row), 201)


@bp.route("/irrigation-events/<event_id>", methods=["GET"])
def read_irrigation(event_id):
    auth(IRRIGATION_ROLES)
    event = service.get_irrigation(event_id)
    return respond_object(derive.serialize_irrigation(event))


@bp.route("/irrigation-events", methods=["GET"])
def list_irrigation():
    auth(IRRIGATION_ROLES)
    rows = service.filtered(store.irrigation_events, (
        ("block_id", "block_id"),
        ("farming_plan_id", "farming_plan_id"),
        ("irrigation_status", "irrigation_status"),
    ))
    items, limit, offset, total = service.page(rows, derive.serialize_irrigation)
    return respond_list(items, limit, offset, total)


RECORD_APPLIED_SCHEMA = [F("applied_inches", "number", ge=0)]


@bp.route("/irrigation-events/<event_id>/record-applied", methods=["POST"])
def record_applied(event_id):
    auth(["VineyardManager", "CrewSupervisor"])
    body = parse_payload(RECORD_APPLIED_SCHEMA)
    event = service.get_irrigation(event_id)
    # rung 12 is vacuously satisfied here: this endpoint carries no crew reference.
    block = store.blocks[event["block_id"]]
    service.require_block_live(block)
    if event["irrigation_status"] != "SCHEDULED":
        raise ApiError("ERR_IRRIGATION_NOT_SCHEDULED", 409)

    event["applied_inches"] = body["applied_inches"]
    event["water_cost"] = r2(
        body["applied_inches"] * block["acres"] * event["water_unit_cost_per_acre_inch"])
    event["irrigation_status"] = "APPLIED"
    event["applied_at"] = store.now_utc()
    store.touch(event)
    store.touch(block)
    return respond_object(derive.serialize_irrigation(event))
