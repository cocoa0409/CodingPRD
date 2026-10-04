"""Weekly Finds buys and store allocations."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

import calc
import svc
from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_date,
    f_int,
    f_num,
    f_str,
    forbid_unless,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("finds", __name__)


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Inclusive date-window overlap."""
    return a_start <= b_end and b_start <= a_end


# ---------------------------------------------------------------------------
# Finds buys
# ---------------------------------------------------------------------------
@bp.post("/v1/finds-buys")
@endpoint("CategoryManager")
def create_finds_buy():
    payload = body()
    product_id = f_str(payload, "product_id")
    week_start = f_date(payload, "week_start_date")
    week_end = f_date(payload, "week_end_date")
    total_quantity = f_int(payload, "total_quantity", minimum=1)
    if week_end < week_start:
        raise ApiError("ERR_VALIDATION",
                       "week_end_date must not precede week_start_date.")
    # tier 4 -- body FK existence
    product = svc.need_product(product_id)
    # tier 8 -- only ACTIVE FINDS products may be bought
    if product["kind"] != "FINDS" or product["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCT_NOT_ACTIVE")
    buy = new_row(
        "FindsBuy",
        product_id=product["id"],
        week_start_date=week_start.isoformat(),
        week_end_date=week_end.isoformat(),
        total_quantity=total_quantity,
        allocated_quantity=0,
        remaining_quantity=0,
        status="PLANNED",
    )
    db.finds_buys[buy["id"]] = buy
    return respond_object(dump(buy), 201)


@bp.get("/v1/finds-buys")
@endpoint("CategoryManager", "OperationsAdmin", "StoreManager")
def list_finds_buys():
    product_id = q_str("product_id")
    status = q_enum("status", calc.FINDS_BUY_STATUSES)
    rows = sort_created(list(db.finds_buys.values()))
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows)


@bp.get("/v1/finds-buys/<buy_id>")
@endpoint("CategoryManager", "OperationsAdmin", "StoreManager")
def read_finds_buy(buy_id):
    buy = svc.need_finds_buy(buy_id)
    if g.role == "StoreManager":
        forbid_unless(g.user_id in db.stores)
    return respond_object(dump(buy))


@bp.post("/v1/finds-buys/<buy_id>/allocations")
@endpoint("CategoryManager")
def plan_allocations(buy_id):
    buy = svc.need_finds_buy(buy_id)
    payload = body()
    # tier 5 -- state admissibility
    if buy["status"] == "PLANNED":
        if not any(s["status"] == "ACTIVE" for s in db.stores.values()):
            raise ApiError("ERR_INVALID_STATE")
    elif buy["status"] == "ALLOCATED":
        pass  # superseding re-plan; OCC-guarded below
    else:
        raise ApiError("ERR_FINDS_NO_REPLENISHMENT")
    # OCC: a stale view of the buy cannot re-plan
    expected = f_int(payload, "expected_finds_buy_version", minimum=0)
    if expected != buy["version"]:
        raise ApiError("ERR_STALE_VERSION")
    svc.plan_allocations(buy)
    # PRD §4: action endpoints and modifications of existing resources return HTTP 200
    return respond_object(dump(buy))


@bp.get("/v1/finds-buys/<buy_id>/allocations")
@endpoint("CategoryManager", "OperationsAdmin", "StoreManager")
def list_buy_allocations(buy_id):
    buy = svc.need_finds_buy(buy_id)
    rows = svc.allocations_of_buy(buy["id"])
    if g.role == "StoreManager":
        rows = [a for a in rows if a["store_id"] == g.user_id]
    return paginate(rows)


@bp.post("/v1/finds-buys/<buy_id>/activate")
@endpoint("CategoryManager")
def activate_finds_buy(buy_id):
    buy = svc.need_finds_buy(buy_id)
    # tier 5 -- state admissibility
    if buy["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE")
    # tier 7 -- temporal: sale-window exclusivity per store
    for allocation in svc.allocations_of_buy(buy["id"]):
        for other in svc.allocations_of_store(allocation["store_id"]):
            if other["id"] == allocation["id"]:
                continue
            if other["status"] not in ("ON_SALE", "CLEARANCE"):
                continue
            if _windows_overlap(
                buy["week_start_date"],
                buy["week_end_date"],
                other["sale_start_date"],
                other["sale_end_date"],
            ):
                raise ApiError("ERR_SALE_WINDOW_CONFLICT")
    # tier 8 -- structural: conservation and live product
    if buy["allocated_quantity"] != buy["total_quantity"]:
        raise ApiError("ERR_ALLOCATION_INCOMPLETE")
    product = db.products[buy["product_id"]]
    if product["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCT_NOT_ACTIVE")
    for allocation in svc.allocations_of_buy(buy["id"]):
        allocation["status"] = "ON_SALE"
        allocation["sale_start_date"] = buy["week_start_date"]
        allocation["sale_end_date"] = buy["week_end_date"]
        touch(allocation)
    buy["status"] = "ON_SALE"
    touch(buy)
    return respond_object(dump(buy))


@bp.post("/v1/finds-buys/<buy_id>/close")
@endpoint("CategoryManager")
def close_finds_buy(buy_id):
    buy = svc.need_finds_buy(buy_id)
    # tier 5 -- state admissibility
    if buy["status"] != "ON_SALE":
        raise ApiError("ERR_INVALID_STATE")
    allocations = svc.allocations_of_buy(buy["id"])
    if any(a["status"] == "ON_SALE" for a in allocations):
        raise ApiError("ERR_INVALID_STATE")
    # tier 7 -- temporal: the week must have ended on the logical clock
    from core import parse_date

    if db.clock.date() <= parse_date(buy["week_end_date"]):
        raise ApiError("ERR_WINDOW_OVERLAP",
                       "The buy cannot close before its week has ended.")
    for allocation in allocations:
        if allocation["status"] == "CLEARANCE":
            allocation["status"] = "CLOSED"
            touch(allocation)
    buy["status"] = "CLOSED"
    touch(buy)
    svc.recompute_sell_through_for_buy(buy)
    return respond_object(dump(buy))


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------
@bp.get("/v1/allocations/<allocation_id>")
@endpoint("CategoryManager", "OperationsAdmin", "StoreManager")
def read_allocation(allocation_id):
    allocation = svc.need_allocation(allocation_id)
    if g.role == "StoreManager":
        forbid_unless(allocation["store_id"] == g.user_id)
    return respond_object(dump(allocation))


@bp.post("/v1/allocations/<allocation_id>/sell")
@endpoint("StoreManager")
def sell_allocation(allocation_id):
    allocation = svc.need_allocation(allocation_id)
    forbid_unless(allocation["store_id"] == g.user_id)
    payload = body()
    quantity = f_int(payload, "quantity", minimum=1)
    # tier 5 -- state admissibility
    if allocation["status"] not in ("ON_SALE", "CLEARANCE"):
        raise ApiError("ERR_INVALID_STATE")
    # tier 7 -- temporal: the sell must fall inside the current sale window
    from core import parse_date

    today = db.clock.date()
    if not (
        parse_date(allocation["sale_start_date"])
        <= today
        <= parse_date(allocation["sale_end_date"])
    ):
        raise ApiError("ERR_SALE_WINDOW_INACTIVE")
    # tier 9 -- fiscal: never sell past the remainder
    if quantity > allocation["remaining_quantity"]:
        raise ApiError("ERR_ALLOCATION_EXHAUSTED")
    svc.sell_from_allocation(allocation, quantity)
    return respond_object(dump(allocation))


@bp.post("/v1/allocations/<allocation_id>/clearance")
@endpoint("StoreManager")
def clearance_allocation(allocation_id):
    allocation = svc.need_allocation(allocation_id)
    forbid_unless(allocation["store_id"] == g.user_id)
    payload = body()
    markdown = f_num(payload, "clearance_markdown_pct")
    clearance_start = f_date(payload, "clearance_start_date")
    clearance_end = f_date(payload, "clearance_end_date")
    if not (Decimal("0") < markdown < Decimal("1")):
        raise ApiError("ERR_VALIDATION",
                       "clearance_markdown_pct must be strictly between 0 and 1.")
    if clearance_end < clearance_start:
        raise ApiError("ERR_VALIDATION",
                       "clearance_end_date must not precede clearance_start_date.")
    # tier 5 -- state admissibility
    if allocation["status"] != "ON_SALE":
        raise ApiError("ERR_INVALID_STATE")
    if allocation["remaining_quantity"] <= 0:
        raise ApiError("ERR_INVALID_STATE")
    # tier 7 -- temporal: the mandatory gap day
    from core import parse_date

    earliest = parse_date(allocation["sale_end_date"]) + timedelta(days=1)
    if clearance_start < earliest:
        raise ApiError("ERR_CLEARANCE_GAP_VIOLATION")
    buy = db.finds_buys[allocation["finds_buy_id"]]
    product = db.products[buy["product_id"]]
    allocation["clearance_markdown_pct"] = markdown
    allocation["clearance_value_cents"] = calc.clearance_value(
        product["price_cents"], markdown, allocation["remaining_quantity"]
    )
    allocation["sale_start_date"] = clearance_start.isoformat()
    allocation["sale_end_date"] = clearance_end.isoformat()
    allocation["status"] = "CLEARANCE"
    touch(allocation)
    return respond_object(dump(allocation))


@bp.get("/v1/stores/<store_id>/finds-allocations")
@endpoint("StoreManager", "OperationsAdmin", "CategoryManager")
def list_store_allocations(store_id):
    store = svc.need_store(store_id)
    if g.role == "StoreManager":
        forbid_unless(g.user_id == store["id"])
    status = q_enum("status", calc.ALLOCATION_STATUSES)
    rows = svc.allocations_of_store(store["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows)
