"""Budget allocations (PRD 3.2)."""

from flask import Blueprint

import calc
from db import db, new_row, touch
from errors import ApiError
from response import created_response, object_response
from routes.common import (
    ALL_ROLES,
    PREFIX,
    created_asc,
    get_allocation,
    get_brand,
    get_customer,
    get_program,
    page,
)
from validators import (
    authenticate,
    body_fields,
    get_enum,
    get_int,
    get_money,
    get_string,
    no_body,
    pagination,
    query_enum,
    query_value,
)

bp = Blueprint("allocations", __name__)

DIRECTOR = "TradeMarketingDirector"
ANALYST = "TradeFinanceAnalyst"
EVENT_TYPES = ("SEASONAL", "EVERYDAY", "NEW_ITEM")
ALLOCATION_STATUSES = ("DRAFT", "APPROVED")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")


@bp.post(PREFIX + "/budget-allocations")
def create_allocation():
    authenticate([DIRECTOR, ANALYST])
    data = body_fields(required=[
        "program_id", "customer_id", "brand_id", "event_type",
        "planned_amount", "baseline_units", "planned_incremental_units",
    ])
    program_id = get_string(data, "program_id")
    customer_id = get_string(data, "customer_id")
    brand_id = get_string(data, "brand_id")
    event_type = get_enum(data, "event_type", EVENT_TYPES)
    planned_amount = get_money(data, "planned_amount", strictly_positive=True)
    baseline_units = get_int(data, "baseline_units", minimum=0)
    incremental_units = get_int(data, "planned_incremental_units", minimum=0)

    # rung 21, in the reference-resolution order of PRD 2.7
    program = get_program(program_id)
    brand = get_brand(brand_id)
    customer = get_customer(customer_id)

    # rung 40
    if program["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_LOCKED")
    # rung 53 - only SUSPENDED blocks planning
    if customer["trading_status"] == "SUSPENDED":
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD")
    # rung 60
    if brand["program_id"] != program_id or customer["program_id"] != program_id:
        raise ApiError("ERR_BRAND_PROGRAM_MISMATCH")
    # rung 97
    allocated = calc.program_allocated_amount(program)
    if allocated + planned_amount > program["total_budget_amount"]:
        raise ApiError("ERR_PROGRAM_BUDGET_EXCEEDED")

    row = new_row()
    row.update({
        "program_id": program_id,
        "customer_id": customer_id,
        "brand_id": brand_id,
        "event_type": event_type,
        "planned_amount": planned_amount,
        "baseline_units": baseline_units,
        "planned_incremental_units": incremental_units,
        "status": "DRAFT",
        "overspend_event_count": 0,
    })
    db.allocations[row["id"]] = row
    touch(program)
    return created_response(calc.allocation_out(row))


@bp.get(PREFIX + "/budget-allocations/<allocation_id>")
def read_allocation(allocation_id):
    authenticate(ALL_ROLES)
    no_body()
    return object_response(calc.allocation_out(get_allocation(allocation_id)))


@bp.get(PREFIX + "/budget-allocations")
def list_allocations():
    authenticate(ALL_ROLES)
    limit, offset = pagination([
        "program_id", "customer_id", "brand_id", "event_type", "status", "posture",
    ])
    program_id = query_value("program_id")
    customer_id = query_value("customer_id")
    brand_id = query_value("brand_id")
    event_type = query_enum("event_type", EVENT_TYPES)
    status = query_enum("status", ALLOCATION_STATUSES)
    posture = query_enum("posture", POSTURES)
    rows = list(db.allocations.values())
    if program_id is not None:
        get_program(program_id)
        rows = [r for r in rows if r["program_id"] == program_id]
    if brand_id is not None:
        get_brand(brand_id)
        rows = [r for r in rows if r["brand_id"] == brand_id]
    if customer_id is not None:
        get_customer(customer_id)
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if posture is not None:
        rows = [r for r in rows if calc.allocation_posture(r) == posture]
    return page(created_asc(rows), limit, offset, calc.allocation_out)


@bp.post(PREFIX + "/budget-allocations/<allocation_id>/approve")
def approve_allocation(allocation_id):
    authenticate([DIRECTOR])
    no_body()
    alloc = get_allocation(allocation_id)
    program = db.programs.get(alloc["program_id"])
    # rung 40
    if program is not None and program["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_LOCKED")
    if alloc["status"] != "DRAFT":
        raise ApiError("ERR_ALLOCATION_NOT_APPROVED")
    alloc["status"] = "APPROVED"
    touch(alloc)
    return object_response(calc.allocation_out(alloc))
