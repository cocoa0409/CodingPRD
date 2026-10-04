# Sales order and order line routes (PRD 3.4).
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import constants as C
import derive
from auth import require_customer_owns, require_roles
from envelope import list_response, success
from errors import (
    ApiError,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_LAST_ORDER_DATE_PASSED,
    ERR_NO_PUBLISHED_PRICING,
    ERR_PART_NOT_ORDERABLE,
)
from lookups import get_customer, get_order, get_order_line, get_part
from serialize import order_line_public, order_public
from store import store
from validate import (
    as_int_at_least,
    as_str,
    bad,
    check_unknown_fields,
    get_body,
    require_fields,
)

bp = Blueprint("orders", __name__)

_CREATE_ALLOWED = {"customer_id", "lines"}
_LINE_ALLOWED = {"part_id", "quantity"}
_ORDERABLE_LIFECYCLES = ("ACTIVE", "NRND", "EOL_ANNOUNCED")


@bp.post("/orders")
def create_order():
    uid, role = require_roles("Customer")
    body = get_body(required=True)
    # Row 2 ownership: the body's customer_id must equal X-User-ID.
    if "customer_id" in body and body["customer_id"] is not None:
        require_customer_owns(body["customer_id"], uid, role)
    # Row 3 existence in the global left-to-right type order: part, customer.
    if isinstance(body.get("lines"), list):
        for entry in body["lines"]:
            if isinstance(entry, dict) and entry.get("part_id") is not None:
                get_part(entry["part_id"])
    if "customer_id" in body and body["customer_id"] is not None:
        customer = get_customer(body["customer_id"])
    # Row 4 schema.
    require_fields(body, ["customer_id", "lines"])
    check_unknown_fields(body, _CREATE_ALLOWED)
    as_str(body["customer_id"], "customer_id")
    raw_lines = body["lines"]
    if not isinstance(raw_lines, list):
        bad("Field lines must be an array")
    parsed_lines = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            bad("Each line must be an object")
        check_unknown_fields(entry, _LINE_ALLOWED)
        require_fields(entry, ["part_id", "quantity"])
        line_part_id = as_str(entry["part_id"], "lines.part_id")
        line_qty = as_int_at_least(entry["quantity"], "lines.quantity", 1)
        parsed_lines.append((line_part_id, line_qty))

    order = {
        "customer_id": customer["id"],
        "channel": customer["channel"],  # channel snapshot at creation
        "status": "DRAFT",
        "subtotal_cents": None,
        "service_fee_cents": 0,
        "total_cents": None,
        "submitted_at": None,
    }
    order.update(store.stamp())
    store.orders[order["id"]] = order
    for line_part_id, line_qty in parsed_lines:
        line = {
            "order_id": order["id"],
            "part_id": line_part_id,
            "quantity": line_qty,
            "unit_price_cents": None,
            "line_total_cents": None,
            "awarded_units": 0,
            "allocation_run_id": None,
            "allocation_rank": None,
            "allocation_priority_score": None,
        }
        line.update(store.stamp())
        store.order_lines[line["id"]] = line
    return success(order_public(order), 201)


@bp.get("/orders")
def list_orders():
    uid, role = require_roles("PlatformAdmin", "ChannelManager", "SupplyPlanner", "Customer")
    customer_filter = request.args.get("customer_id")
    status_filter = request.args.get("status")
    if role == "Customer":
        # A Customer principal sees only its own orders.
        customer_filter = uid
    orders = list(store.orders.values())
    if customer_filter is not None:
        orders = [o for o in orders if o["customer_id"] == customer_filter]
    if status_filter is not None:
        orders = [o for o in orders if o["status"] == status_filter]
    orders.sort(key=lambda o: o["seq"])
    return list_response(orders, order_public)


@bp.get("/orders/<order_id>")
def fetch_order(order_id):
    uid, role = require_roles("PlatformAdmin", "ChannelManager", "SupplyPlanner", "Customer")
    order = get_order(order_id)
    require_customer_owns(order["customer_id"], uid, role)
    return success(order_public(order))


def _submit_order(order):
    """POST /orders/{id}/submit — the pivotal fork (PRD 3.4)."""
    if order["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT order can be submitted")
    lines = derive.order_lines_of(order["id"])
    if not lines:
        raise ApiError(ERR_INVALID_STATE, 409, "Order has no lines")
    customer = store.customers[order["customer_id"]]
    now = store.now()

    # Row 8 (clock window): EOL_ANNOUNCED parts past their last_order_date.
    for line in lines:
        part = store.parts[line["part_id"]]
        if part["lifecycle_status"] == "EOL_ANNOUNCED":
            notice = derive.announced_notice_for_part(part["id"])
            if notice is not None and now > notice["last_order_date"]:
                raise ApiError(ERR_LAST_ORDER_DATE_PASSED, 422, "The part's last order date has passed")

    # Row 9, in written order: orderable lifecycle, then published pricing.
    for line in lines:
        part = store.parts[line["part_id"]]
        if part["lifecycle_status"] not in _ORDERABLE_LIFECYCLES:
            raise ApiError(ERR_PART_NOT_ORDERABLE, 422, "Part %s is not orderable (lifecycle %s)" % (part["part_number"], part["lifecycle_status"]))
    for line in lines:
        part = store.parts[line["part_id"]]
        if derive.published_schedule(part["id"]) is None:
            raise ApiError(ERR_NO_PUBLISHED_PRICING, 422, "No PUBLISHED pricing schedule is effective for part %s" % part["part_number"])

    # calc_order_totals — pinned evaluation order, per-line round-half-up.
    discount = Decimal(str(customer["discount_pct"]))
    subtotal = 0
    for line in lines:
        part = store.parts[line["part_id"]]
        schedule = derive.published_schedule(part["id"])
        unit_price = derive.tier_for_quantity(schedule, line["quantity"])["unit_price_cents"]
        raw = Decimal(unit_price) * Decimal(line["quantity"]) * (Decimal(1) - discount)
        line_total = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        line["unit_price_cents"] = unit_price
        line["line_total_cents"] = line_total
        subtotal += line_total
    service_fee = 0
    if (
        customer["tier"] == "SMALL"
        and order["channel"] == "DIRECT_ONLINE"
        and subtotal < C.MIN_ORDER_SUBTOTAL_CENTS
    ):
        service_fee = C.SMALL_ORDER_FEE_CENTS
    total = subtotal + service_fee

    # Row 10: credit gate (inclusive boundary).
    exposure = derive.customer_open_exposure(customer["id"])
    if exposure + total > customer["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 422, "Order total would exceed the customer's credit limit")

    # Auto-award: sequential in line order; a line is fully awarded when its
    # part is not in SHORTAGE and available stock covers the full quantity.
    pending_reserved = {}
    for line in lines:
        part = store.parts[line["part_id"]]
        extra = pending_reserved.get(part["id"], 0)
        _, posture = derive.coverage_and_posture(part, extra_reserved=extra)
        available = part["on_hand_units"] - derive.part_reserved_units(part["id"]) - extra
        if posture != "SHORTAGE" and available >= line["quantity"]:
            line["awarded_units"] = line["quantity"]
            pending_reserved[part["id"]] = extra + line["quantity"]
        store.touch(line)

    order["subtotal_cents"] = subtotal
    order["service_fee_cents"] = service_fee
    order["total_cents"] = total
    order["submitted_at"] = now
    fully_allocated = all(line["awarded_units"] == line["quantity"] for line in lines)
    order["status"] = "ALLOCATED" if fully_allocated else "BACKORDERED"
    store.touch(order)


@bp.post("/orders/<order_id>/submit")
def submit_order(order_id):
    uid, role = require_roles("Customer")
    order = get_order(order_id)
    require_customer_owns(order["customer_id"], uid, role)
    body = get_body(required=False)
    check_unknown_fields(body, set())
    _submit_order(order)
    return success(order_public(order))


@bp.post("/orders/<order_id>/ship")
def ship_order(order_id):
    require_roles("SupplyPlanner")
    order = get_order(order_id)
    body = get_body(required=False)
    check_unknown_fields(body, set())
    if order["status"] != "ALLOCATED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ALLOCATED order can be shipped")
    for line in derive.order_lines_of(order["id"]):
        part = store.parts[line["part_id"]]
        part["on_hand_units"] -= line["awarded_units"]
        store.touch(part)
    order["status"] = "SHIPPED"
    store.touch(order)
    return success(order_public(order))


@bp.post("/orders/<order_id>/cancel")
def cancel_order(order_id):
    uid, role = require_roles("Customer", "ChannelManager")
    order = get_order(order_id)
    require_customer_owns(order["customer_id"], uid, role)
    body = get_body(required=False)
    check_unknown_fields(body, set())
    if order["status"] not in ("DRAFT", "ALLOCATED", "BACKORDERED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Order in status %s cannot be cancelled" % order["status"])
    if order["status"] in ("ALLOCATED", "BACKORDERED"):
        for line in derive.order_lines_of(order["id"]):
            line["awarded_units"] = 0
            store.touch(line)
    order["status"] = "CANCELLED"
    store.touch(order)
    return success(order_public(order))


@bp.get("/order-lines")
def list_order_lines():
    require_roles("PlatformAdmin", "ChannelManager", "SupplyPlanner")
    order_filter = request.args.get("order_id")
    part_filter = request.args.get("part_id")
    lines = list(store.order_lines.values())
    if order_filter is not None:
        lines = [l for l in lines if l["order_id"] == order_filter]
    if part_filter is not None:
        lines = [l for l in lines if l["part_id"] == part_filter]
    lines.sort(key=lambda l: l["seq"])
    return list_response(lines, order_line_public)


@bp.get("/order-lines/<line_id>")
def fetch_order_line(line_id):
    require_roles("PlatformAdmin", "ChannelManager", "SupplyPlanner")
    return success(order_line_public(get_order_line(line_id)))
