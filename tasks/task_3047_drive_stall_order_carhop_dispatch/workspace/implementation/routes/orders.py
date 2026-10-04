"""Order, OrderLine, and payment-axis endpoints (PRD 3.3-3.5, 3.7, 3.8)."""
from decimal import Decimal, ROUND_HALF_UP

from db import db, now
from errors import not_found, raise_error, invalid_request, invalid_state
from middleware import (
    require_auth,
    body_json,
    get_str,
    get_int,
    get_enum,
    get_bool,
    get_str_list,
    pagination_params,
    sort_by_created,
)
from response import success_object, success_array, success_no_data
from serializers import order as ser_order, order_line as ser_line
from services import (
    make_record,
    touch,
    get_location,
    get_order_nested,
    order_lines,
    recompute_draft_pricing,
    place_order,
    cancel_order,
)
from . import orders_bp

CHANNELS = ["STALL_INTERCOM", "APP_CHECKIN", "DRIVE_THRU", "PATIO"]
ORDER_STATUSES = [
    "DRAFT",
    "PLACED",
    "PREPARING",
    "READY",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "CANCELLED",
]
PAYMENT_STATUSES = ["UNPAID", "AUTHORIZED", "CAPTURED", "VOIDED", "REFUNDED"]
ORDER_READ_ROLES = ["Customer", "ShiftManager", "Carhop", "KitchenStaff", "PlatformAdmin"]
MAX_PREPARING = 8


def _new_order_record(loc, channel, customer_id, stall_id):
    rec = make_record()
    rec.update(
        {
            "location_id": loc["id"],
            "stall_id": stall_id,
            "customer_id": customer_id,
            "channel": channel,
            "status": "DRAFT",
            "payment_status": "UNPAID",
            # Directly created (drive-thru) drafts anchor their check-in at
            # creation: offer windows and rush-expiry read checked_in_at.
            "checked_in_at": now(),
            "placed_at": None,
            "ready_at": None,
            "delivered_at": None,
            "service_target_seconds": None,
            "late_flag": False,
            "subtotal_cents": 0,
            "offer_discount_cents": 0,
            "tax_cents": 0,
            "tip_cents": 0,
            "total_cents": 0,
            "total_tendered_cents": 0,
            "delivery_run_id": None,
            "run_position": None,
            "checked_in_rush_index": None,
        }
    )
    return rec


@orders_bp.route("/locations/<locationId>/orders", methods=["POST"])
def create_order(locationId):
    require_auth(["Customer", "ShiftManager"])
    loc = get_location(locationId)
    body = body_json()
    channel = body.get("channel", "DRIVE_THRU")
    if channel not in CHANNELS:
        invalid_request("channel must be a valid order channel")
    if channel != "DRIVE_THRU":
        invalid_request("Only DRIVE_THRU orders may be created directly")
    customer_id = body.get("customer_id")
    if customer_id is not None:
        if not isinstance(customer_id, str):
            invalid_request("customer_id must be a string")
        if customer_id not in db.customers:
            not_found("Customer not found")
    rec = _new_order_record(loc, "DRIVE_THRU", customer_id, None)
    db.orders[rec["id"]] = rec
    return success_object(ser_order(rec), 201)


@orders_bp.route("/locations/<locationId>/orders", methods=["GET"])
def list_orders(locationId):
    require_auth(["ShiftManager", "Carhop", "KitchenStaff", "PlatformAdmin"])
    from flask import request

    get_location(locationId)
    status = request.args.get("status")
    channel = request.args.get("channel")
    payment_status = request.args.get("payment_status")
    if status is not None and status not in ORDER_STATUSES:
        invalid_request("status must be a valid order status")
    if channel is not None and channel not in CHANNELS:
        invalid_request("channel must be a valid order channel")
    if payment_status is not None and payment_status not in PAYMENT_STATUSES:
        invalid_request("payment_status must be a valid payment status")
    orders = [o for o in db.orders.values() if o["location_id"] == locationId]
    if status is not None:
        orders = [o for o in orders if o["status"] == status]
    if channel is not None:
        orders = [o for o in orders if o["channel"] == channel]
    if payment_status is not None:
        orders = [o for o in orders if o["payment_status"] == payment_status]
    for key in ("stall_id", "customer_id", "delivery_run_id"):
        v = request.args.get(key)
        if v is not None:
            orders = [o for o in orders if o[key] == v]
    orders = sort_by_created(orders)
    limit, offset = pagination_params()
    total = len(orders)
    page = orders[offset : offset + limit]
    return success_array([ser_order(o) for o in page], limit, offset, total)


@orders_bp.route("/locations/<locationId>/orders/<orderId>", methods=["GET"])
def get_order(locationId, orderId):
    require_auth(ORDER_READ_ROLES)
    loc, order = get_order_nested(locationId, orderId)
    return success_object(ser_order(order))


@orders_bp.route("/locations/<locationId>/orders/<orderId>/lines", methods=["POST"])
def add_line(locationId, orderId):
    require_auth(["Customer", "ShiftManager"])
    loc, order = get_order_nested(locationId, orderId)
    body = body_json()
    menu_item_id = body.get("menu_item_id")
    if menu_item_id is None or not isinstance(menu_item_id, str):
        invalid_request("menu_item_id is required")
    item = db.menu_items.get(menu_item_id)
    if item is None:
        not_found("MenuItem not found")
    if order["status"] != "DRAFT":
        invalid_state("Order lines may only be added while the order is DRAFT")
    if item["status"] == "RETIRED":
        raise_error("ERR_MENU_ITEM_RETIRED", "Cannot add a RETIRED menu item to an order")
    quantity = get_int(body, "quantity", required=True, minimum=1)
    size_code = get_str(body, "size_option_code")
    addin_codes = get_str_list(body, "addin_option_codes", default=[])

    size_opt = None
    if item["size_scheme"] == "DRINK_SIZES":
        if size_code is None:
            raise_error("ERR_SIZE_REQUIRED", "A size option is required for DRINK_SIZES items")
        size_opt = _find_option_by_code(size_code)
        if (
            size_opt is None
            or size_opt["status"] != "ACTIVE"
            or not size_opt["is_size"]
        ):
            raise_error("ERR_OPTION_INVALID", "Size option is not ACTIVE or is not a size option")
    elif size_code is not None:
        size_opt = _find_option_by_code(size_code)
        if size_opt is None or not size_opt["is_size"]:
            raise_error("ERR_OPTION_INVALID", "size_option_code must name a size option")

    unit = item["base_price_cents"]
    if item["size_scheme"] == "DRINK_SIZES" and size_opt is not None:
        unit += size_opt["size_upcharge_cents"]
    for code in addin_codes:
        opt = _find_option_by_code(code)
        if opt is None or opt["status"] != "ACTIVE":
            raise_error("ERR_OPTION_INVALID", "Add-in option is not ACTIVE")
        if opt["is_size"]:
            raise_error("ERR_OPTION_INVALID", "Size options are not valid add-ins")
        if opt["applies_to_category"] not in ("ANY", item["category"]):
            raise_error("ERR_OPTION_INVALID", "Add-in option is not applicable to this category")
        unit += opt["price_cents"]

    rec = make_record()
    rec.update(
        {
            "order_id": order["id"],
            "menu_item_id": item["id"],
            "quantity": quantity,
            "size_option_code": size_code,
            "addin_option_codes": addin_codes,
            "unit_price_cents": unit,
            "extended_price_cents": unit * quantity,
            "happy_hour_priced": False,
        }
    )
    db.order_lines[rec["id"]] = rec
    recompute_draft_pricing(order)
    return success_object(ser_line(rec), 201)


def _find_option_by_code(code):
    for o in db.customization_options.values():
        if o["code"] == code:
            return o
    return None


@orders_bp.route("/locations/<locationId>/orders/<orderId>/lines", methods=["GET"])
def list_lines(locationId, orderId):
    require_auth(ORDER_READ_ROLES)
    loc, order = get_order_nested(locationId, orderId)
    lines = sort_by_created(order_lines(order["id"]))
    limit, offset = pagination_params()
    total = len(lines)
    page = lines[offset : offset + limit]
    return success_array([ser_line(l) for l in page], limit, offset, total)


@orders_bp.route("/locations/<locationId>/orders/<orderId>/lines/<lineId>", methods=["DELETE"])
def delete_line(locationId, orderId, lineId):
    require_auth(["Customer", "ShiftManager"])
    loc, order = get_order_nested(locationId, orderId)
    line = db.order_lines.get(lineId)
    if line is None or line["order_id"] != order["id"]:
        not_found("OrderLine not found")
    if order["status"] != "DRAFT":
        invalid_state("Order lines may only be removed while the order is DRAFT")
    del db.order_lines[lineId]
    recompute_draft_pricing(order)
    return success_no_data(204)


@orders_bp.route("/locations/<locationId>/orders/<orderId>/place", methods=["POST"])
def place(locationId, orderId):
    require_auth(["Customer", "ShiftManager"])
    loc, order = get_order_nested(locationId, orderId)
    body = body_json()
    offer_code = body.get("offer_code")
    if offer_code is not None and not isinstance(offer_code, str):
        invalid_request("offer_code must be a string")
    fallback_confirmed = get_bool(body, "fallback_confirmed", default=False)
    place_order(order, loc, offer_code, fallback_confirmed)
    return success_object(ser_order(order))


@orders_bp.route("/locations/<locationId>/orders/<orderId>/start_preparation", methods=["POST"])
def start_preparation(locationId, orderId):
    require_auth(["KitchenStaff", "ShiftManager"])
    loc, order = get_order_nested(locationId, orderId)
    if order["status"] != "PLACED":
        invalid_state("Order is not PLACED")
    preparing = sum(
        1
        for o in db.orders.values()
        if o["location_id"] == loc["id"] and o["status"] == "PREPARING"
    )
    if preparing >= MAX_PREPARING:
        raise_error("ERR_KITCHEN_SATURATED", "Kitchen is at capacity")
    order["status"] = "PREPARING"
    touch(order)
    return success_object(ser_order(order))


@orders_bp.route("/locations/<locationId>/orders/<orderId>/mark_ready", methods=["POST"])
def mark_ready(locationId, orderId):
    require_auth(["KitchenStaff", "ShiftManager"])
    loc, order = get_order_nested(locationId, orderId)
    if order["status"] != "PREPARING":
        invalid_state("Order is not PREPARING")
    order["status"] = "READY"
    order["ready_at"] = now()
    touch(order)
    return success_object(ser_order(order))


@orders_bp.route("/locations/<locationId>/orders/<orderId>/authorize_payment", methods=["POST"])
def authorize_payment(locationId, orderId):
    require_auth(["Customer", "ShiftManager"])
    loc, order = get_order_nested(locationId, orderId)
    if order["payment_status"] != "UNPAID":
        invalid_state("Payment is not UNPAID")
    if order["status"] not in ("DRAFT", "PLACED", "PREPARING", "READY"):
        invalid_state("Payment may only be authorized while the order is DRAFT, PLACED, PREPARING, or READY")
    order["payment_status"] = "AUTHORIZED"
    touch(order)
    return success_object(ser_order(order))


@orders_bp.route("/locations/<locationId>/orders/<orderId>/capture_payment", methods=["POST"])
def capture_payment(locationId, orderId):
    require_auth(["Customer", "Carhop", "ShiftManager"])
    loc, order = get_order_nested(locationId, orderId)
    body = body_json()
    explicit_tip = body.get("tip_cents")
    if explicit_tip is not None:
        if not isinstance(explicit_tip, int) or isinstance(explicit_tip, bool):
            invalid_request("tip_cents must be an integer")
        if explicit_tip < 0:
            invalid_request("tip_cents must be >= 0")
    if order["payment_status"] != "AUTHORIZED":
        invalid_state("Payment is not AUTHORIZED")

    if explicit_tip is not None:
        tip = explicit_tip
    elif order["customer_id"] is not None:
        customer = db.customers.get(order["customer_id"])
        if customer is not None and customer["stored_tip_default_pct"] > 0:
            tip = int(
                (
                    Decimal(order["total_cents"])
                    * Decimal(str(customer["stored_tip_default_pct"]))
                ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
        else:
            tip = 0
    else:
        tip = 0

    tender = order["total_cents"] + tip
    customer = db.customers.get(order["customer_id"]) if order["customer_id"] else None
    if customer is not None and customer["wallet_credit_cents"] > 0:
        debit = min(customer["wallet_credit_cents"], tender)
        customer["wallet_credit_cents"] -= debit
        touch(customer)

    carhop_id = None
    if order["delivery_run_id"] is not None:
        run = db.delivery_runs.get(order["delivery_run_id"])
        if run is not None:
            carhop_id = run["carhop_id"]

    order["tip_cents"] = tip
    order["total_tendered_cents"] = tender
    order["payment_status"] = "CAPTURED"
    touch(order)

    tip_rec = make_record()
    tip_rec.update(
        {
            "order_id": order["id"],
            "carhop_id": carhop_id,
            "tip_cents": tip,
            "status": "RECORDED",
            "adjusted_tip_cents": None,
        }
    )
    db.tip_records[tip_rec["id"]] = tip_rec
    if carhop_id is not None:
        carhop = db.carhops.get(carhop_id)
        if carhop is not None:
            carhop["tips_outstanding_cents"] += tip
            touch(carhop)
    return success_object(ser_order(order))


@orders_bp.route("/locations/<locationId>/orders/<orderId>/refund", methods=["POST"])
def refund(locationId, orderId):
    require_auth(["ShiftManager"])
    loc, order = get_order_nested(locationId, orderId)
    body = body_json()
    refund_mode = get_enum(body, "refund_mode", ["STORE_CREDIT", "ORIGINAL_PAYMENT"], required=True)
    manager_override = get_bool(body, "manager_override", default=False)
    if order["payment_status"] != "CAPTURED":
        invalid_state("Payment is not CAPTURED")
    if order["status"] != "DELIVERED" and not manager_override:
        raise_error(
            "ERR_PAYMENT_NOT_CAPTURED",
            "Refunding a non-delivered order requires manager_override",
        )
    order["payment_status"] = "REFUNDED"
    touch(order)
    tip_rec = None
    for t in db.tip_records.values():
        if t["order_id"] == order["id"]:
            tip_rec = t
            break
    if tip_rec is not None and tip_rec["status"] == "RECORDED":
        tip_rec["status"] = "VOIDED"
        touch(tip_rec)
        if tip_rec["carhop_id"] is not None:
            carhop = db.carhops.get(tip_rec["carhop_id"])
            if carhop is not None:
                carhop["tips_outstanding_cents"] -= tip_rec["tip_cents"]
                touch(carhop)
    if refund_mode == "STORE_CREDIT" and order["customer_id"] is not None:
        customer = db.customers.get(order["customer_id"])
        if customer is not None:
            customer["wallet_credit_cents"] += order["total_cents"]
            touch(customer)
    return success_object(ser_order(order))


@orders_bp.route("/locations/<locationId>/orders/<orderId>/cancel", methods=["POST"])
def cancel(locationId, orderId):
    user_id, role = require_auth(["Customer", "ShiftManager"])
    loc, order = get_order_nested(locationId, orderId)
    if order["status"] == "DRAFT":
        pass
    elif order["status"] in ("PLACED", "PREPARING", "READY"):
        if role != "ShiftManager":
            from errors import raise_error as _re

            _re("ERR_FORBIDDEN", "Only a ShiftManager may cancel a non-DRAFT order")
        if order["payment_status"] not in ("UNPAID", "AUTHORIZED", "VOIDED"):
            raise_error(
                "ERR_PAYMENT_CAPTURED_REQUIRES_REFUND",
                "A captured order must be refunded, not cancelled",
            )
    else:
        invalid_state("Order cannot be cancelled from its current state")
    cancel_order(order)
    return success_object(ser_order(order))
