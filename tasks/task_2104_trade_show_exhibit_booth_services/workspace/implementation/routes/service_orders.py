"""Service orders: deadline tiering, the pricing waterfall and two status dimensions."""
from flask import Blueprint

import db
import guards
import response
from errors import ApiError
from middleware import ANY_ROLE, own_exhibitor, require_roles
from services import calc, state
from validation import json_body, parse_dt, require_row

bp = Blueprint("service_orders", __name__)
store = db.store

SERVICE_TYPES = ("ELECTRICAL", "RIGGING", "MATERIAL_HANDLING", "CLEANING",
                 "INSTALL_DISMANTLE")
WINDOW_REQUIRED = ("RIGGING", "INSTALL_DISMANTLE")
ORDERING_STATUSES = ("OPEN_FOR_ORDERS", "ADVANCE_CLOSED", "MOVE_IN", "ON_SITE")
LIVE_WINDOW_STATUSES = ("PENDING", "CONFIRMED", "SCHEDULED", "HELD")
FULFILLMENT_TERMINAL = ("CANCELLED",)


def lines_of_order(order_id):
    rows = [line for line in store.order_lines.values()
            if line["service_order_id"] == order_id]
    return sorted(rows, key=lambda row: row["line_seq"])


def _validate_lines(raw_lines):
    parsed = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each line must be an object")
        line_seq = _line_int(entry, "line_seq")
        code = entry.get("catalog_item_code")
        if not isinstance(code, str) or not code.strip():
            raise ApiError("ERR_INVALID_REQUEST",
                           "catalog_item_code is required on every line")
        unit_qty = _line_int(entry, "unit_qty")
        unit_rate = _line_int(entry, "unit_rate_cents")
        discount = entry.get("discount_pct", 0)
        if discount is None:
            discount = 0
        if isinstance(discount, bool) or not isinstance(discount, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", "discount_pct must be a number")
        if discount < 0:
            raise ApiError("ERR_INVALID_REQUEST", "discount_pct must not be negative")
        parsed.append({
            "line_seq": line_seq,
            "catalog_item_code": code,
            "unit_qty": unit_qty,
            "unit_rate_cents": unit_rate,
            "discount_pct": discount,
        })
    return parsed


def _line_int(entry, field):
    value = entry.get(field)
    if value is None:
        raise ApiError("ERR_INVALID_REQUEST", "%s is required on every line" % field)
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if value < 0:
        raise ApiError("ERR_INVALID_REQUEST", "%s must not be negative" % field)
    return value


def reprice(order, tier, multiplier):
    """Re-run line pricing and the waterfall onto the order row."""
    lines = lines_of_order(order["id"])
    subtotal = calc.price_lines(lines, multiplier)
    figures = calc.order_waterfall(subtotal)
    order["deadline_tier"] = tier
    order["tier_multiplier"] = multiplier
    order.update(figures)
    return order


@bp.post("/service-orders")
def create_order():
    require_roles("Exhibitor", "ShowOperations")
    body = json_body()
    peeked_booth = store.booths.get(body.peek_str("booth_id"))
    own_exhibitor(peeked_booth["exhibitor_id"] if peeked_booth else None)

    booth_id = body.string("booth_id")
    service_type = body.enum("service_type", SERVICE_TYPES)
    raw_lines = body.array("lines")
    expected_version = body.integer("expected_booth_version")
    window_start = body.datetime_str("window_start", required=False, default=None)
    window_end = body.datetime_str("window_end", required=False, default=None)
    if service_type in WINDOW_REQUIRED and (window_start is None or window_end is None):
        raise ApiError("ERR_INVALID_REQUEST",
                       "window_start and window_end are required for %s" % service_type)
    parsed_lines = _validate_lines(raw_lines)

    booth = require_row(store.booths, booth_id, "ERR_BOOTH_NOT_FOUND", "Booth")
    show = store.shows.get(booth["show_id"])

    guards.occ(expected_version, booth["version"], "ERR_STALE_BOOTH_VERSION")
    guards.show_accepting(show, ORDERING_STATUSES)
    guards.booth_not_frozen(booth)

    if window_start is not None and window_end is not None:
        _check_window(booth_id, parse_dt(window_start), parse_dt(window_end))

    guards.not_empty(parsed_lines, "lines")
    sequences = sorted(line["line_seq"] for line in parsed_lines)
    if sequences != list(range(1, len(sequences) + 1)):
        raise ApiError("ERR_INVALID_LINE_SEQUENCE",
                       "line_seq values must be unique and contiguous from 1")

    ordered_at = db.now_stamp()
    tier, multiplier = calc.deadline_tier(
        db.now_dt(), (parse_dt(show["discount_deadline"]), parse_dt(show["move_in_start"])))

    order = {
        "id": db.new_id(),
        "booth_id": booth_id,
        "invoice_id": None,
        "service_type": service_type,
        "window_start": window_start,
        "window_end": window_end,
        "ordered_at": ordered_at,
        "deadline_tier": tier,
        "tier_multiplier": multiplier,
        "subtotal_cents": 0,
        "volume_discount_cents": 0,
        "discounted_base_cents": 0,
        "service_fee_cents": 0,
        "total_cents": 0,
        "fulfillment_status": "PENDING",
        "billing_status": "UNBILLED",
    }

    line_rows = []
    for parsed in sorted(parsed_lines, key=lambda row: row["line_seq"]):
        line = {
            "id": db.new_id(),
            "service_order_id": order["id"],
            "line_seq": parsed["line_seq"],
            "catalog_item_code": parsed["catalog_item_code"],
            "unit_qty": parsed["unit_qty"],
            "unit_rate_cents": parsed["unit_rate_cents"],
            "discount_pct": parsed["discount_pct"],
            "line_total_cents": 0,
        }
        line_rows.append(line)

    subtotal = calc.price_lines(line_rows, multiplier)
    order.update(calc.order_waterfall(subtotal))

    exhibitor = store.exhibitors.get(booth["exhibitor_id"])
    _check_credit(exhibitor, order["total_cents"])

    db.stamp_common(order)
    store.service_orders[order["id"]] = order
    for line in line_rows:
        line["created_at"] = db.wall_now()
        line["_seq"] = order["_seq"]
        store.order_lines[line["id"]] = line
    db.touch(booth)
    return response.created(order)


def _check_window(booth_id, new_start, new_end):
    for order in store.service_orders.values():
        if order["booth_id"] != booth_id:
            continue
        if order["fulfillment_status"] not in LIVE_WINDOW_STATUSES:
            continue
        if order.get("window_start") is None or order.get("window_end") is None:
            continue
        existing_start = parse_dt(order["window_start"])
        existing_end = parse_dt(order["window_end"])
        if new_start <= existing_end and existing_start <= new_end:
            raise ApiError("ERR_BOOTH_WINDOW_CONFLICT",
                           "The requested floor window collides with a live order")


def _check_credit(exhibitor, new_order_total):
    if exhibitor is None:
        return
    exposure = int(exhibitor["account_balance_cents"]) + int(new_order_total)
    for order in store.service_orders.values():
        if order["billing_status"] != "UNBILLED":
            continue
        booth = store.booths.get(order["booth_id"])
        if booth is not None and booth["exhibitor_id"] == exhibitor["id"]:
            exposure += int(order["total_cents"])
    if exposure > int(exhibitor["credit_limit_cents"]):
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED",
                       "Projected exposure exceeds the exhibitor credit limit")


@bp.get("/service-orders/<order_id>")
def get_order(order_id):
    require_roles(ANY_ROLE)
    order = store.service_orders.get(order_id)
    own_exhibitor(_order_exhibitor(order))
    order = require_row(store.service_orders, order_id, "ERR_SERVICE_ORDER_NOT_FOUND",
                        "Service order")
    return response.ok(order)


@bp.get("/service-orders")
def list_orders():
    require_roles(ANY_ROLE)
    rows = list(store.service_orders.values())
    rows = response.filter_rows(rows, "booth_id", "invoice_id", "fulfillment_status",
                                "billing_status")
    return response.listing(rows)


@bp.get("/service-orders/<order_id>/lines")
def list_lines(order_id):
    require_roles(ANY_ROLE)
    response.pagination_params()
    order = store.service_orders.get(order_id)
    own_exhibitor(_order_exhibitor(order))
    require_row(store.service_orders, order_id, "ERR_SERVICE_ORDER_NOT_FOUND",
                "Service order")
    return response.listing(lines_of_order(order_id))


@bp.post("/service-orders/<order_id>/fulfillment")
def fulfillment(order_id):
    require_roles("ShowOperations", "Exhibitor")
    body = json_body()
    order = store.service_orders.get(order_id)
    own_exhibitor(_order_exhibitor(order))
    to_status = body.enum("to_status", ("PENDING", "CONFIRMED", "SCHEDULED", "DELIVERED",
                                        "HELD", "CANCELLED"))
    body.string("note", required=False, default=None)
    order = require_row(store.service_orders, order_id, "ERR_SERVICE_ORDER_NOT_FOUND",
                        "Service order")
    booth = store.booths.get(order["booth_id"])
    show = store.shows.get(booth["show_id"]) if booth else None

    edges = {
        "CONFIRMED": ("PENDING",),
        "SCHEDULED": ("CONFIRMED",),
        "DELIVERED": ("SCHEDULED",),
        "CANCELLED": ("PENDING", "CONFIRMED", "SCHEDULED", "HELD"),
    }
    guards.transition(order["fulfillment_status"], FULFILLMENT_TERMINAL,
                      edges.get(to_status, ()))

    if to_status == "CONFIRMED":
        guards.show_accepting(show, ORDERING_STATUSES)
        guards.booth_not_frozen(booth)
    elif to_status == "SCHEDULED":
        guards.booth_not_frozen(booth)
    elif to_status == "DELIVERED":
        guards.show_accepting(show, ("MOVE_IN", "ON_SITE", "MOVE_OUT"))
    elif to_status == "CANCELLED":
        if order["billing_status"] not in ("UNBILLED", "CREDITED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "An invoiced order may not be cancelled")

    order["fulfillment_status"] = to_status
    db.touch(order)

    if to_status == "CANCELLED":
        cancelled_any = False
        for call in store.labor_calls.values():
            if call.get("service_order_id") == order_id and \
                    call["status"] in ("REQUESTED", "DISPATCHED"):
                call["status"] = "CANCELLED"
                db.touch(call)
                cancelled_any = True
        if cancelled_any and show is not None:
            state.recompute_show_aggregates(show)

    return response.ok(order)


def _order_exhibitor(order):
    if not order:
        return None
    booth = store.booths.get(order["booth_id"])
    return booth["exhibitor_id"] if booth else None
