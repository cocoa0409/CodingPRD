"""Volume facts and the weekly accrual ledger (PRD 3.7)."""

from flask import Blueprint

import calc
import services
from calc import ZERO
from db import db, new_row, touch
from errors import ApiError
from response import created_response, object_response
from routes.common import (
    ALL_ROLES,
    PREFIX,
    created_asc,
    get_accrual,
    get_brand,
    get_customer,
    get_fact,
    get_promotion,
    page,
    period_then_created,
)
from validators import (
    authenticate,
    body_fields,
    get_date,
    get_enum,
    get_int,
    get_money,
    get_string,
    no_body,
    pagination,
    query_date,
    query_enum,
    query_value,
)

bp = Blueprint("ledger", __name__)

ANALYST = "TradeFinanceAnalyst"
FACT_TYPES = ("SHIPMENT", "CONSUMPTION")
SOURCES = ("EDI_852", "EDI_856", "MANUAL")
ENTRY_TYPES = ("ACCRUAL", "REVERSAL")
ENTRY_STATUSES = ("POSTED", "REVERSED")


# --------------------------------------------------------------------------
# volume facts
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/volume-facts")
def create_fact():
    authenticate([ANALYST])
    data = body_fields(required=[
        "customer_id", "brand_id", "fact_type", "period_start", "units", "source",
    ])
    customer_id = get_string(data, "customer_id")
    brand_id = get_string(data, "brand_id")
    fact_type = get_enum(data, "fact_type", FACT_TYPES)
    period_start = get_date(data, "period_start")
    units = get_int(data, "units", minimum=0)
    source = get_enum(data, "source", SOURCES)

    # rung 21, in the canonical reference order of PRD 2.7
    get_brand(brand_id)
    get_customer(customer_id)
    # rung 64
    for row in db.facts.values():
        if (row["customer_id"] == customer_id and row["brand_id"] == brand_id
                and row["fact_type"] == fact_type
                and row["period_start"] == period_start):
            raise ApiError("ERR_VOLUME_FACT_DUPLICATE")
    # rung 70
    if period_start.weekday() != 0:
        raise ApiError("ERR_WINDOW_NOT_WEEK_ALIGNED")

    row = new_row(versioned=False)
    row.update({
        "customer_id": customer_id,
        "brand_id": brand_id,
        "fact_type": fact_type,
        "period_start": period_start,
        "units": units,
        "source": source,
    })
    db.facts[row["id"]] = row
    return created_response(calc.fact_out(row))


@bp.get(PREFIX + "/volume-facts/<fact_id>")
def read_fact(fact_id):
    authenticate(ALL_ROLES)
    no_body()
    return object_response(calc.fact_out(get_fact(fact_id)))


@bp.get(PREFIX + "/volume-facts")
def list_facts():
    authenticate(ALL_ROLES)
    limit, offset = pagination(["customer_id", "brand_id", "fact_type", "period_start"])
    customer_id = query_value("customer_id")
    brand_id = query_value("brand_id")
    fact_type = query_enum("fact_type", FACT_TYPES)
    period_start = query_date("period_start")
    rows = list(db.facts.values())
    if brand_id is not None:
        get_brand(brand_id)
        rows = [r for r in rows if r["brand_id"] == brand_id]
    if customer_id is not None:
        get_customer(customer_id)
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if fact_type is not None:
        rows = [r for r in rows if r["fact_type"] == fact_type]
    if period_start is not None:
        rows = [r for r in rows if r["period_start"] == period_start]
    return page(period_then_created(rows), limit, offset, calc.fact_out)


# --------------------------------------------------------------------------
# accrual postings
# --------------------------------------------------------------------------

@bp.post(PREFIX + "/promotions/<promotion_id>/accruals")
def post_accrual(promotion_id):
    authenticate([ANALYST])
    data = body_fields(required=["period_start"])
    period_start = get_date(data, "period_start")
    promo = get_promotion(promotion_id)
    # rung 43
    if promo["lifecycle_status"] not in ("LIVE", "ENDED", "ANALYZED"):
        raise ApiError("ERR_PROMOTION_STATE_INVALID")
    # rung 66 - the duplicate bar survives a reversal
    for entry in calc.accruals_of_promotion(promotion_id):
        if entry["entry_type"] == "ACCRUAL" and entry["period_start"] == period_start:
            raise ApiError("ERR_ACCRUAL_PERIOD_DUPLICATE")
    # rung 70
    if period_start.weekday() != 0:
        raise ApiError("ERR_WINDOW_NOT_WEEK_ALIGNED")
    method, effective, fact_units, lines, amount = services.accrual_components(
        promo, period_start)
    # rung 72
    if not (promo["window_start"] <= effective < promo["window_end"]):
        raise ApiError("ERR_ACCRUAL_WINDOW_MISMATCH")

    row = new_row()
    row.update({
        "promotion_id": promotion_id,
        "period_start": period_start,
        "method": method,
        "fact_units": fact_units,
        "entry_type": "ACCRUAL",
        "amount": amount,
        "status": "POSTED",
        "reverses_entry_id": None,
        "reversal_reason": None,
        "tactic_line_amounts": lines,
    })
    db.accruals[row["id"]] = row
    touch(promo)
    services.apply_spend_cascade(promo)
    alloc = db.allocations.get(promo["allocation_id"])
    if alloc is not None:
        touch(alloc)
    return created_response(calc.accrual_out(row))


@bp.get(PREFIX + "/accruals/<accrual_id>")
def read_accrual(accrual_id):
    authenticate(ALL_ROLES)
    no_body()
    return object_response(calc.accrual_out(get_accrual(accrual_id)))


@bp.get(PREFIX + "/accruals")
def list_accruals():
    authenticate(ALL_ROLES)
    limit, offset = pagination(["promotion_id", "reverses_entry_id", "entry_type", "status"])
    promotion_id = query_value("promotion_id")
    reverses_entry_id = query_value("reverses_entry_id")
    entry_type = query_enum("entry_type", ENTRY_TYPES)
    status = query_enum("status", ENTRY_STATUSES)
    rows = list(db.accruals.values())
    if promotion_id is not None:
        get_promotion(promotion_id)
        rows = [r for r in rows if r["promotion_id"] == promotion_id]
    if reverses_entry_id is not None:
        get_accrual(reverses_entry_id)
        rows = [r for r in rows if r["reverses_entry_id"] == reverses_entry_id]
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(period_then_created(rows), limit, offset, calc.accrual_out)


@bp.post(PREFIX + "/accruals/<accrual_id>/reverse")
def reverse_accrual(accrual_id):
    authenticate([ANALYST])
    data = body_fields(required=["amount", "reversal_reason"])
    amount = get_money(data, "amount")
    reason = get_string(data, "reversal_reason", min_len=1)
    entry = get_accrual(accrual_id)
    # rung 46
    if entry["entry_type"] != "ACCRUAL" or entry["status"] != "POSTED":
        raise ApiError("ERR_ACCRUAL_ENTRY_ALREADY_REVERSED")
    # rung 90 - a reversal mirrors its original exactly
    if amount <= ZERO or amount != entry["amount"]:
        raise ApiError("ERR_REVERSAL_EXCEEDS_ENTRY_AMOUNT")

    entry["status"] = "REVERSED"
    touch(entry)
    mirror = new_row()
    mirror.update({
        "promotion_id": entry["promotion_id"],
        "period_start": entry["period_start"],
        "method": entry["method"],
        "fact_units": 0,
        "entry_type": "REVERSAL",
        "amount": entry["amount"],
        "status": "POSTED",
        "reverses_entry_id": entry["id"],
        "reversal_reason": reason,
        "tactic_line_amounts": [],
    })
    db.accruals[mirror["id"]] = mirror
    promo = db.promotions.get(entry["promotion_id"])
    if promo is not None:
        touch(promo)
        services.apply_spend_cascade(promo)
        alloc = db.allocations.get(promo["allocation_id"])
        if alloc is not None:
            touch(alloc)
    return created_response(calc.accrual_out(mirror))
