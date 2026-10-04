"""Handheld order entry: orders and order lines."""

from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, request

import db as store
import services as svc
from errors import (
    ERR_DELIVERY_LINE_NOT_ON_ORDER,
    ERR_DELIVERY_WINDOW_MISSED,
    ERR_FRESHNESS_GUARANTEE_VIOLATION,
    ERR_INSUFFICIENT_TRUCK_STOCK,
    ERR_INVALID_STATE,
    ERR_NO_SCHEDULED_STOP,
    ERR_ORDER_NOT_FOUND,
    ERR_PRODUCT_NOT_ALLOCATED,
    ERR_PRODUCT_NOT_FOUND,
    ERR_ROUTE_DAY_NOT_IN_PROGRESS,
    ERR_STALE_VERSION,
    ERR_STORE_NOT_ACTIVE,
    ERR_VALIDATION,
    err,
)
from helpers import (
    WEEKDAYS,
    auth,
    body,
    clock_now_iso,
    filter_sort_page,
    get,
    new_record,
    opt_enum,
    opt_number,
    req_field,
    req_int,
    req_str,
    require_role,
    touch,
)
from response import list_response, success

bp = Blueprint("orders", __name__)


def line_total(qty, price_cents, discount_pct):
    dec = Decimal(qty) * Decimal(price_cents) * (Decimal(1) - Decimal(str(discount_pct)))
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _parse_lines(data, required=True):
    lines = data.get("lines")
    if lines is None:
        if required:
            raise err(ERR_VALIDATION, "Missing required field: lines")
        return None
    if not isinstance(lines, list):
        raise err(ERR_VALIDATION, "lines must be an array")
    parsed = []
    for entry in lines:
        if not isinstance(entry, dict):
            raise err(ERR_VALIDATION, "each line must be an object")
        product_id = req_str(entry, "product_id")
        qty = req_int(entry, "qty_ordered_cases")
        discount = opt_number(entry, "line_discount_pct", 0)
        if qty <= 0:
            raise err(ERR_VALIDATION, "qty_ordered_cases must be > 0")
        if not (0 <= discount < 1):
            raise err(ERR_VALIDATION, "line_discount_pct must satisfy 0 <= x < 1")
        parsed.append(
            {"product_id": product_id, "qty_ordered_cases": qty, "line_discount_pct": discount}
        )
    return parsed


def _product_exists_or_404(product_id):
    if product_id not in store.db["products"]:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found: %s" % product_id)
    return store.db["products"][product_id]


def _weekday_covered(route_id, store_id, service_date):
    from datetime import date

    weekday = WEEKDAYS[date.fromisoformat(service_date).weekday()]
    for a in store.db["assignments"].values():
        if (
            a["route_id"] == route_id
            and a["store_id"] == store_id
            and a["status"] == "ACTIVE"
            and weekday in a["service_weekdays"]
        ):
            return True
    return False


def _write_lines(order, parsed):
    """Replace an order's line set wholesale and recompute totals."""
    for lid in [lid for lid, l in store.db["order_lines"].items() if l["order_id"] == order["id"]]:
        del store.db["order_lines"][lid]
    gross = 0
    for idx, p in enumerate(parsed, start=1):
        product = _product_exists_or_404(p["product_id"])
        total = line_total(p["qty_ordered_cases"], product["case_price_cents"], p["line_discount_pct"])
        line = new_record(common=False)
        line.update(
            order_id=order["id"],
            product_id=p["product_id"],
            qty_ordered_cases=p["qty_ordered_cases"],
            line_discount_pct=p["line_discount_pct"],
            qty_delivered_cases=0,
            line_total_cents=total,
            line_seq=idx,
        )
        store.db["order_lines"][line["id"]] = line
        gross += total
    order["gross_total_cents"] = gross


def _order_lines(order_id):
    lines = [l for l in store.db["order_lines"].values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: l["line_seq"])
    return lines


@bp.post("/dsd/orders")
def create_order():
    uid, role = auth()
    require_role(role, "RouteSalesRep")
    data = body()
    route_day_id = req_str(data, "route_day_id")
    store_id = req_str(data, "store_id")
    order_type = opt_enum(data, "order_type", ("STANDARD", "EVENT_SURGE"), "STANDARD")
    parsed = _parse_lines(data, required=True)
    # body FK existence in declared input order
    day = get("route_days", route_day_id)
    st = get("stores", store_id)
    for p in parsed:
        _product_exists_or_404(p["product_id"])
    if not parsed:
        raise err(ERR_VALIDATION, "lines must be non-empty")
    if order_type == "EVENT_SURGE" and not day["is_event_day"]:
        raise err(ERR_VALIDATION, "EVENT_SURGE orders permitted only on event days")
    # state preconditions
    if day["status"] != "IN_PROGRESS":
        raise err(ERR_ROUTE_DAY_NOT_IN_PROGRESS, "Route day is not IN_PROGRESS")
    if st["status"] != "ACTIVE":
        raise err(ERR_STORE_NOT_ACTIVE, "Store is not ACTIVE")
    # temporal: scheduled-stop coverage for this route+store+weekday
    if not _weekday_covered(day["route_id"], store_id, day["service_date"]):
        raise err(ERR_NO_SCHEDULED_STOP, "No ACTIVE assignment covers this stop")
    # referential allocation: an OPEN lot exists per line product
    for p in parsed:
        if not svc.open_lots_for(day["id"], p["product_id"]):
            raise err(ERR_PRODUCT_NOT_ALLOCATED, "Product not allocated on this route day")
    rec = new_record()
    rec.update(
        route_day_id=route_day_id,
        store_id=store_id,
        order_type=order_type,
        status="DRAFT",
        gross_total_cents=0,
        submitted_at=None,
        delivered_at=None,
    )
    store.db["orders"][rec["id"]] = rec
    _write_lines(rec, parsed)
    return success(rec, 201)


@bp.get("/dsd/orders/<orderId>")
def get_order(orderId):
    auth()
    return success(get("orders", orderId), 200)


@bp.get("/dsd/orders")
def list_orders():
    auth()
    items, limit, offset, total = filter_sort_page(
        "orders",
        {
            "route_day_id": request.args.get("route_day_id"),
            "store_id": request.args.get("store_id"),
            "status": request.args.get("status"),
        },
    )
    return list_response(items, limit, offset, total)


@bp.put("/dsd/orders/<orderId>")
def revise_order(orderId):
    uid, role = auth()
    require_role(role, "RouteSalesRep")
    order = get("orders", orderId)
    data = body()
    parsed = _parse_lines(data, required=True)
    expected = data.get("expected_store_order_version")
    if expected is not None and expected != order["version"]:
        raise err(ERR_STALE_VERSION, "Order version has advanced")
    if order["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Only DRAFT orders may be revised")
    if not parsed:
        raise err(ERR_VALIDATION, "lines must be non-empty")
    day = get("route_days", order["route_day_id"])
    for p in parsed:
        _product_exists_or_404(p["product_id"])
    for p in parsed:
        if not svc.open_lots_for(day["id"], p["product_id"]):
            raise err(ERR_PRODUCT_NOT_ALLOCATED, "Product not allocated on this route day")
    _write_lines(order, parsed)
    touch(order)
    return success(order, 200)


@bp.post("/dsd/orders/<orderId>/submit")
def submit_order(orderId):
    uid, role = auth()
    require_role(role, "RouteSalesRep")
    order = get("orders", orderId)
    if order["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Only DRAFT orders may be submitted")
    day = get("route_days", order["route_day_id"])
    st = get("stores", order["store_id"])
    if day["status"] != "IN_PROGRESS":
        raise err(ERR_ROUTE_DAY_NOT_IN_PROGRESS, "Route day is not IN_PROGRESS")
    if st["status"] != "ACTIVE":
        raise err(ERR_STORE_NOT_ACTIVE, "Store is not ACTIVE")
    minute = store.clock.minute_of_day()
    if not (st["delivery_window_start_minute"] <= minute < st["delivery_window_end_minute"]):
        raise err(ERR_DELIVERY_WINDOW_MISSED, "Outside the store delivery window")
    if not _order_lines(order["id"]):
        raise err(ERR_VALIDATION, "Order has no lines")
    order["status"] = "SUBMITTED"
    order["submitted_at"] = clock_now_iso()
    touch(order)
    return success(order, 200)


@bp.post("/dsd/orders/<orderId>/unsubmit")
def unsubmit_order(orderId):
    uid, role = auth()
    require_role(role, "RouteSalesRep")
    order = get("orders", orderId)
    if order["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Only SUBMITTED orders may be unsubmitted")
    order["status"] = "DRAFT"
    touch(order)
    return success(order, 200)


@bp.post("/dsd/orders/<orderId>/deliver")
def deliver_order(orderId):
    uid, role = auth()
    require_role(role, "RouteSalesRep")
    order = get("orders", orderId)
    if order["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Only SUBMITTED orders may be delivered")
    day = get("route_days", order["route_day_id"])
    if day["status"] != "IN_PROGRESS":
        raise err(ERR_ROUTE_DAY_NOT_IN_PROGRESS, "Route day is not IN_PROGRESS")
    data = body()
    payload = req_field(data, "lines")
    if not isinstance(payload, list):
        raise err(ERR_VALIDATION, "lines must be an array")
    order_lines = _order_lines(order["id"])
    by_product = {}
    for line in order_lines:
        by_product.setdefault(line["product_id"], line)
    requested = {}
    for entry in payload:
        if not isinstance(entry, dict):
            raise err(ERR_VALIDATION, "each line must be an object")
        product_id = req_str(entry, "product_id")
        qty = req_int(entry, "qty_delivered_cases")
        if qty < 0:
            raise err(ERR_VALIDATION, "qty_delivered_cases must be >= 0")
        requested[product_id] = requested.get(product_id, 0) + qty
    # Priority (7): freshness guarantee — evaluated before the (9) referential
    # line-on-order check. If fulfilling any requested product would require a
    # lot with days_to_expiry <= 5, freshness fails first.
    for product_id, qty in requested.items():
        if qty == 0:
            continue
        candidates = svc.freshness_eligible_lots(day["id"], product_id, day)
        available = sum(svc.lot_remaining(l) for l in candidates)
        if available < qty:
            all_open = [
                l
                for l in svc.open_lots_for(day["id"], product_id)
                if svc.lot_remaining(l) > 0
            ]
            total_remaining = sum(svc.lot_remaining(l) for l in all_open)
            if total_remaining >= qty:
                raise err(
                    ERR_FRESHNESS_GUARANTEE_VIOLATION,
                    "Fulfilling this line requires a lot with days_to_expiry <= 5",
                )
    # Priority (9): referential — every payload line must reference a product
    # present on the order, and no line may exceed its ordered quantity.
    for product_id, qty in requested.items():
        if product_id not in by_product:
            raise err(ERR_DELIVERY_LINE_NOT_ON_ORDER, "Product not on the order")
        if qty > by_product[product_id]["qty_ordered_cases"]:
            raise err(ERR_VALIDATION, "qty_delivered_cases exceeds qty_ordered_cases")
    # preflight all lines before mutating anything (atomicity)
    plans = {}
    for product_id, qty in requested.items():
        if qty == 0:
            plans[product_id] = []
            continue
        candidates = svc.freshness_eligible_lots(day["id"], product_id, day)
        available = sum(svc.lot_remaining(l) for l in candidates)
        if available < qty:
            raise err(ERR_INSUFFICIENT_TRUCK_STOCK, "Insufficient freshness-eligible stock")
        plan = []
        remaining = qty
        for lot in candidates:
            if remaining == 0:
                break
            take = min(svc.lot_remaining(lot), remaining)
            plan.append((lot, take))
            remaining -= take
        plans[product_id] = plan
    # commit
    for line in order_lines:
        line["qty_delivered_cases"] = requested.get(line["product_id"], 0)
    for product_id, plan in plans.items():
        for lot, take in plan:
            lot["delivered_cases"] += take
            lot["remaining_cases"] = svc.lot_remaining(lot)
            touch(lot)
    order["status"] = "DELIVERED"
    order["delivered_at"] = clock_now_iso()
    touch(order)
    svc.recompute_day_totals(day)
    svc.ledger_moved(day["id"])
    return success(order, 200)


@bp.post("/dsd/orders/<orderId>/cancel")
def cancel_order(orderId):
    uid, role = auth()
    require_role(role, "RouteSalesRep")
    order = get("orders", orderId)
    if order["status"] not in ("DRAFT", "SUBMITTED"):
        raise err(ERR_INVALID_STATE, "Order cannot be cancelled from %s" % order["status"])
    order["status"] = "CANCELLED"
    touch(order)
    return success(order, 200)


# ---------------------------------------------------------------------------
# order lines
# ---------------------------------------------------------------------------

@bp.get("/dsd/order-lines/<lineId>")
def get_order_line(lineId):
    auth()
    rec = store.db["order_lines"].get(lineId)
    if rec is None:
        raise err(ERR_ORDER_NOT_FOUND, "Order line not found: %s" % lineId)
    return success(rec, 200)


@bp.get("/dsd/order-lines")
def list_order_lines():
    auth()
    items, limit, offset, total = filter_sort_page(
        "order_lines",
        {
            "order_id": request.args.get("order_id"),
            "product_id": request.args.get("product_id"),
        },
    )
    return list_response(items, limit, offset, total)
