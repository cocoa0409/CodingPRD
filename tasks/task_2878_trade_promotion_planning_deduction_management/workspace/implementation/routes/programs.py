"""Logical clock, trade programs, brands and retail customers (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint, g

import calc
import services
from calc import ZERO, q2
from db import clock_dt, db, new_row, set_clock, touch
from errors import ApiError, bad_request
from response import created_response, object_response
from routes.common import (
    ALL_ROLES,
    ALL_ROLES_WITH_PORTAL,
    PREFIX,
    created_asc,
    created_desc,
    get_customer,
    get_program,
    page,
)
from validators import (
    authenticate,
    body_fields,
    get_enum,
    get_instant,
    get_int,
    get_money,
    get_string,
    no_body,
    pagination,
    portal_guard,
    query_enum,
    query_int,
    query_value,
)

bp = Blueprint("programs", __name__)

DIRECTOR = "TradeMarketingDirector"
ACCRUAL_METHODS = ("SHIPMENT", "CONSUMPTION")
PROGRAM_STATUSES = ("OPEN", "LOCKED")
CHANNELS = ("GROCERY", "MASS", "CLUB", "DOLLAR")
POLICIES = ("EVIDENCE_BASED", "AGREEMENT_CAP")
TRADING_STATUSES = ("ACTIVE", "CREDIT_HOLD", "SUSPENDED")
AUDIT_STATUSES = ("CLEAR", "AUDIT_IN_PROGRESS", "FINDINGS_OPEN")


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock_endpoint():
    authenticate(ALL_ROLES)
    data = body_fields(required=["current_utc"])
    instant = get_instant(data, "current_utc")
    set_clock(instant)
    from db import clock_instant
    return object_response({"current_utc": clock_instant()})


# --------------------------------------------------------------------------
# trade programs
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/programs")
def create_program():
    authenticate([DIRECTOR])
    data = body_fields(
        required=["fiscal_year", "name", "total_budget_amount"],
        optional=["accrual_method_default"],
    )
    fiscal_year = get_int(data, "fiscal_year", minimum=2020, maximum=2100)
    name = get_string(data, "name", min_len=1, max_len=120)
    total = get_money(data, "total_budget_amount", strictly_positive=True)
    method = get_enum(data, "accrual_method_default", ACCRUAL_METHODS, required=False)
    row = new_row()
    row.update({
        "fiscal_year": fiscal_year,
        "name": name,
        "total_budget_amount": total,
        "accrual_method_default": method or "SHIPMENT",
        "status": "OPEN",
    })
    db.programs[row["id"]] = row
    return created_response(calc.program_out(row))


@bp.get(PREFIX + "/programs/<program_id>")
def read_program(program_id):
    authenticate(ALL_ROLES)
    no_body()
    return object_response(calc.program_out(get_program(program_id)))


@bp.get(PREFIX + "/programs")
def list_programs():
    authenticate(ALL_ROLES)
    limit, offset = pagination(["fiscal_year", "status"])
    fiscal_year = query_int("fiscal_year")
    status = query_enum("status", PROGRAM_STATUSES)
    rows = list(db.programs.values())
    if fiscal_year is not None:
        rows = [r for r in rows if r["fiscal_year"] == fiscal_year]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(created_desc(rows), limit, offset, calc.program_out)


@bp.post(PREFIX + "/programs/<program_id>/lock")
def lock_program(program_id):
    authenticate([DIRECTOR])
    no_body()
    program = get_program(program_id)
    if program["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_LOCKED")
    program["status"] = "LOCKED"
    touch(program)
    rescore_customer_ids = []
    for alloc in calc.allocations_of_program(program["id"]):
        # posture is derived; the lock still repostures every child row and
        # bumps its version (PRD 3.1).
        touch(alloc)
        if alloc["customer_id"] not in rescore_customer_ids:
            rescore_customer_ids.append(alloc["customer_id"])
    # PRD 2.10: the score is recomputed whenever an allocation's posture
    # changes, and FROZEN allocations contribute nothing -- so the lock takes
    # the points a RESTRICTED cell had scored back out of the score.
    for customer_id in rescore_customer_ids:
        customer = db.customers.get(customer_id)
        if customer is not None:
            services.rescore_customer(customer)
    return object_response(calc.program_out(program))


# --------------------------------------------------------------------------
# brands
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/brands")
def create_brand():
    authenticate([DIRECTOR])
    data = body_fields(required=[
        "program_id", "name", "list_price_per_case", "cogs_per_case",
        "baseline_units_per_week",
    ])
    program_id = get_string(data, "program_id")
    name = get_string(data, "name", min_len=1, max_len=120)
    list_price = get_money(data, "list_price_per_case", strictly_positive=True)
    cogs = get_money(data, "cogs_per_case")
    baseline = get_int(data, "baseline_units_per_week", minimum=0)
    if cogs >= list_price:
        raise bad_request("cogs_per_case must be strictly below list_price_per_case.")
    program = get_program(program_id)
    if program["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_LOCKED")
    row = new_row()
    row.update({
        "program_id": program_id,
        "name": name,
        "list_price_per_case": list_price,
        "cogs_per_case": cogs,
        "baseline_units_per_week": baseline,
        "unit_margin": q2(list_price - cogs),
    })
    db.brands[row["id"]] = row
    return created_response(calc.brand_out(row))


@bp.get(PREFIX + "/brands/<brand_id>")
def read_brand(brand_id):
    authenticate(ALL_ROLES)
    no_body()
    from routes.common import get_brand
    return object_response(calc.brand_out(get_brand(brand_id)))


@bp.get(PREFIX + "/brands")
def list_brands():
    authenticate(ALL_ROLES)
    limit, offset = pagination(["program_id"])
    program_id = query_value("program_id")
    rows = list(db.brands.values())
    if program_id is not None:
        get_program(program_id)
        rows = [r for r in rows if r["program_id"] == program_id]
    return page(created_asc(rows), limit, offset, calc.brand_out)


# --------------------------------------------------------------------------
# retail customers
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/customers")
def create_customer():
    authenticate([DIRECTOR])
    data = body_fields(
        required=["program_id", "name", "channel"],
        optional=["deduction_validation_policy"],
    )
    program_id = get_string(data, "program_id")
    name = get_string(data, "name", min_len=1, max_len=120)
    channel = get_enum(data, "channel", CHANNELS)
    policy = get_enum(data, "deduction_validation_policy", POLICIES, required=False)
    get_program(program_id)
    row = new_row()
    row.update({
        "program_id": program_id,
        "name": name,
        "channel": channel,
        "deduction_validation_policy": policy or "EVIDENCE_BASED",
        "trading_status": "ACTIVE",
        "audit_status": "CLEAR",
        "compliance_penalty_points": 0,
        "credit_hold_reason": None,
    })
    db.customers[row["id"]] = row
    return created_response(calc.customer_out(row))


@bp.get(PREFIX + "/customers/<customer_id>")
def read_customer(customer_id):
    authenticate(ALL_ROLES_WITH_PORTAL)
    portal_guard(customer_id)
    no_body()
    return object_response(calc.customer_out(get_customer(customer_id)))


@bp.get(PREFIX + "/customers")
def list_customers():
    authenticate(ALL_ROLES)
    limit, offset = pagination(["program_id", "channel", "trading_status", "audit_status"])
    program_id = query_value("program_id")
    channel = query_enum("channel", CHANNELS)
    trading_status = query_enum("trading_status", TRADING_STATUSES)
    audit_status = query_enum("audit_status", AUDIT_STATUSES)
    rows = list(db.customers.values())
    if program_id is not None:
        get_program(program_id)
        rows = [r for r in rows if r["program_id"] == program_id]
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    if trading_status is not None:
        rows = [r for r in rows if r["trading_status"] == trading_status]
    if audit_status is not None:
        rows = [r for r in rows if r["audit_status"] == audit_status]
    return page(created_asc(rows), limit, offset, calc.customer_out)


@bp.post(PREFIX + "/customers/<customer_id>/credit-hold")
def credit_hold(customer_id):
    authenticate(["DeductionSpecialist", DIRECTOR])
    data = body_fields(required=["reason"])
    reason = get_string(data, "reason", min_len=1)
    customer = get_customer(customer_id)
    if customer["trading_status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD")
    customer["trading_status"] = "CREDIT_HOLD"
    customer["credit_hold_reason"] = reason
    touch(customer)
    return object_response(calc.customer_out(customer))
