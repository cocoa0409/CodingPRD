"""Rework orders: escape-driven creation, close (budget gate), credit (PRD 3.5)."""
from flask import Blueprint

import calc
import svc
from core import (
    ApiError,
    body,
    db,
    endpoint,
    f_int,
    new_row,
    paginate,
    q_enum,
    raw_int,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("rework", __name__, url_prefix="/api")

REWORK_STATUSES = ("OPEN", "CLOSED", "CREDITED")


@bp.post("/quality-escapes/<escape_id>/rework-orders")
@endpoint("QualityInspector")
def create_escape_rework_order(escape_id):
    escape = svc.need_escape(escape_id)
    payload = body()
    # rung 10 -- estimated_hours payload (hours basis for the provisional variant)
    estimated_hours = f_int(payload, "estimated_hours", minimum=1)
    order = svc.create_rework_order(
        escape["aircraft_id"], "QUALITY_ESCAPE", estimated_hours, escape_id=escape["id"]
    )
    return respond_object(svc.dump_rework_order(order), 201)


@bp.get("/aircraft-units/<aircraft_id>/rework-orders")
@endpoint("ProgramAdmin", "ProductionPlanner", "LineManager", "QualityInspector", "DeliveryManager")
def list_aircraft_rework_orders(aircraft_id):
    svc.need_aircraft(aircraft_id)
    source = q_enum("source", calc.REWORK_SOURCES)
    status = q_enum("status", REWORK_STATUSES)
    rows = [ro for ro in db.rework_orders.values() if ro["aircraft_id"] == aircraft_id]
    if source is not None:
        rows = [ro for ro in rows if ro["source"] == source]
    if status is not None:
        rows = [ro for ro in rows if ro["status"] == status]
    return paginate(sort_created(rows), svc.dump_rework_order)


@bp.get("/work-packages/<package_id>/rework-orders")
@endpoint("ProgramAdmin", "LineManager")
def list_package_rework_orders(package_id):
    svc.need_work_package(package_id)
    rows = [ro for ro in db.rework_orders.values() if ro["work_package_id"] == package_id]
    return paginate(sort_created(rows), svc.dump_rework_order)


@bp.get("/quality-escapes/<escape_id>/rework-orders")
@endpoint("ProgramAdmin", "QualityInspector")
def list_escape_rework_orders(escape_id):
    svc.need_escape(escape_id)
    rows = [ro for ro in db.rework_orders.values() if ro["escape_id"] == escape_id]
    return paginate(sort_created(rows), svc.dump_rework_order)


@bp.post("/rework-orders/<order_id>/close")
@endpoint("LineManager")
def close_rework_order(order_id):
    order = svc.need_rework_order(order_id)
    payload = body()
    # rung 5 -- state gate (CREDITED terminal; CLOSED cannot re-close)
    if order["status"] != "OPEN":
        raise ApiError("ERR_INVALID_TRANSITION")
    aircraft = svc.need_aircraft(order["aircraft_id"])
    program = svc.need_program(aircraft["program_id"])
    # rung 9 -- budget gate on the final variant figure
    hours_raw = payload.get("actual_hours")
    parts_raw = payload.get("parts_cents")
    if raw_int(hours_raw) and raw_int(parts_raw):
        final = calc.final_cost(hours_raw, parts_raw)
        if (
            calc.rework_budget_consumed(program["id"]) + final
            > program["rework_budget_total_cents"]
        ):
            raise ApiError("ERR_BUDGET_EXCEEDED")
    # rung 10 -- body shape
    actual_hours = f_int(payload, "actual_hours", minimum=0)
    parts_cents = f_int(payload, "parts_cents", minimum=0)
    # Final variant ignores the provisional estimate entirely (PRD 3.5).
    order["actual_cost_cents"] = calc.final_cost(actual_hours, parts_cents)
    order["status"] = "CLOSED"
    touch(order)
    # Program budget / aircraft total / traveled-work hours all recompute live.
    return respond_object(svc.dump_rework_order(order))


@bp.post("/rework-orders/<order_id>/credit")
@endpoint("LineManager")
def credit_rework_order(order_id):
    order = svc.need_rework_order(order_id)
    if order["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_TRANSITION")
    order["status"] = "CREDITED"
    touch(order)
    # Compensating action: both ledgers drop the order on their live recompute.
    return respond_object(svc.dump_rework_order(order))
