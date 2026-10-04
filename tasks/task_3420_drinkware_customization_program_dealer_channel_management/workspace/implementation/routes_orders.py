"""Customization orders: intake, reads, submit (PROVISIONAL quote + payment
authorization), and cancel (fee/refund + reservation release cascade)."""
from flask import Blueprint, request

from auth import context, forbidden, require_roles
from calc import (
    compute_quote_cents, peak_probe_provisional, promote_waitlist,
    refresh_drop,
)
from constants import CANCEL_FEE_RATE
from decimal import Decimal
from envelope import (
    get_body, new_entity, req_dt, req_enum, req_int, req_str, sort_created,
    success, success_list, touch,
)
from errors import fail
from serialize import ser_order
from store import DB

bp = Blueprint("orders", __name__)

BUYER_TYPES = ("CORPORATE", "INDIVIDUAL")
TECHNOLOGIES = ("LASER", "PAD")


def load_order(order_id):
    o = DB.orders.get(order_id)
    if o is None:
        fail("ERR_ORDER_NOT_FOUND", "no customization order with id %s" % order_id)
    return o


def check_buyer_owns(order, uid, role):
    if role == "Buyer" and order["buyer_ref"] != uid:
        forbidden("Buyer role may act only on its own orders")


@bp.post("/drinkware/customization-orders")
def create_order():
    uid, role = context()
    require_roles(role, ["Buyer"])
    body = get_body()
    buyer_type = req_enum(body, "buyer_type", BUYER_TYPES)
    buyer_ref = req_str(body, "buyer_ref")
    product_line_id = req_str(body, "product_line_id")
    colorway_drop_id = req_str(body, "colorway_drop_id")
    quantity = req_int(body, "quantity", minimum=1)
    declared_colors = req_int(body, "declared_color_count", minimum=1, maximum=8)
    declared_placements = req_int(body, "declared_placement_count", minimum=1, maximum=4)
    print_technology = req_enum(body, "print_technology", TECHNOLOGIES)
    requested_ship_date = req_dt(body, "requested_ship_date")
    if buyer_ref != uid:
        forbidden("buyer_ref must equal the acting Buyer identity")
    if product_line_id not in DB.product_lines:
        fail("ERR_PRODUCT_LINE_NOT_FOUND", "no product line with id %s" % product_line_id)
    if colorway_drop_id not in DB.drops:
        fail("ERR_DROP_NOT_FOUND", "no colorway drop with id %s" % colorway_drop_id)
    # Line status and colorway coherence gates are deliberately deferred to submit.
    order = new_entity({
        "buyer_type": buyer_type,
        "buyer_ref": buyer_ref,
        "product_line_id": product_line_id,
        "colorway_drop_id": colorway_drop_id,
        "quantity": quantity,
        "declared_color_count": declared_colors,
        "declared_placement_count": declared_placements,
        "print_technology": print_technology,
        "requested_ship_date": requested_ship_date,
        "order_state": "ACTIVE",
        "artwork_status": "NO_ART",
        "proof_round": 0,
        "schedule_status": "UNSCHEDULED",
        "payment_status": "UNPAID",
        "return_status": "NONE",
        "return_reason": None,
        "return_resolution": None,
        "affected_unit_count": None,
        "slot_id": None,
        "reservation_status": "NONE",
        "reserved_minutes": 0,
        "quote_variant": "NONE",
        "peak_applied": False,
        "provisional_quote_cents": None,
        "final_quote_cents": None,
        "cancellation_fee_cents": 0,
        "refund_cents": 0,
        "qc_fail_count": 0,
        "completed_at": None,
    })
    DB.orders[order["id"]] = order
    return success(ser_order(order), 201)


@bp.get("/drinkware/customization-orders/<order_id>")
def get_order(order_id):
    uid, role = context()
    require_roles(role, ["Buyer", "PlatformAdmin", "ProductionLead",
                         "PrepressTech", "CustomerCare", "WarrantyAgent"])
    order = load_order(order_id)
    check_buyer_owns(order, uid, role)
    return success(ser_order(order))


@bp.get("/drinkware/customization-orders")
def list_orders():
    uid, role = context()
    require_roles(role, ["Buyer", "PlatformAdmin", "ProductionLead", "CustomerCare"])
    buyer_ref = request.args.get("buyer_ref")
    product_line_id = request.args.get("product_line_id")
    colorway_drop_id = request.args.get("colorway_drop_id")
    slot_id = request.args.get("slot_id")
    schedule_status = request.args.get("schedule_status")
    reservation_status = request.args.get("reservation_status")
    if role == "Buyer":
        buyer_ref = uid  # filter forced to the acting buyer
    items = sort_created(list(DB.orders.values()))
    if buyer_ref is not None:
        items = [o for o in items if o["buyer_ref"] == buyer_ref]
    if product_line_id is not None:
        items = [o for o in items if o["product_line_id"] == product_line_id]
    if colorway_drop_id is not None:
        items = [o for o in items if o["colorway_drop_id"] == colorway_drop_id]
    if slot_id is not None:
        items = [o for o in items if o["slot_id"] == slot_id]
    if schedule_status is not None:
        items = [o for o in items if o["schedule_status"] == schedule_status]
    if reservation_status is not None:
        items = [o for o in items if o["reservation_status"] == reservation_status]
    return success_list([ser_order(o) for o in items])


@bp.post("/drinkware/customization-orders/<order_id>/submit")
def submit_order(order_id):
    uid, role = context()
    require_roles(role, ["Buyer"])
    order = load_order(order_id)
    check_buyer_owns(order, uid, role)
    get_body()
    if order["order_state"] != "ACTIVE" or order["payment_status"] != "UNPAID":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an ACTIVE, UNPAID order can be submitted")
    line = DB.product_lines.get(order["product_line_id"])
    if line is None:
        fail("ERR_PRODUCT_LINE_NOT_FOUND",
             "no product line with id %s" % order["product_line_id"])
    if line["status"] != "ACTIVE":
        fail("ERR_PRODUCT_LINE_DISCONTINUED",
             "orders on a DISCONTINUED product line cannot be submitted")
    drop = DB.drops.get(order["colorway_drop_id"])
    if drop is None:
        fail("ERR_DROP_NOT_FOUND",
             "no colorway drop with id %s" % order["colorway_drop_id"])
    refresh_drop(drop)
    if drop["product_line_id"] != order["product_line_id"] or drop["status"] == "CLOSED":
        fail("ERR_COLORWAY_NOT_AVAILABLE",
             "the drop must belong to the order's product line and not be CLOSED")
    if order["quantity"] < line["min_custom_quantity"]:
        fail("ERR_BELOW_MINIMUM_QUANTITY",
             "quantity is below the product line's min_custom_quantity")
    peak = peak_probe_provisional(order)
    total = compute_quote_cents(
        line, order["buyer_type"], order["quantity"],
        order["declared_color_count"], order["declared_placement_count"], peak)
    order["provisional_quote_cents"] = total
    order["quote_variant"] = "PROVISIONAL"
    order["peak_applied"] = peak
    order["payment_status"] = "AUTHORIZED"
    touch(order)
    return success(ser_order(order))


@bp.post("/drinkware/customization-orders/<order_id>/cancel")
def cancel_order(order_id):
    uid, role = context()
    require_roles(role, ["Buyer", "PlatformAdmin"])
    order = load_order(order_id)
    check_buyer_owns(order, uid, role)
    get_body()
    if order["schedule_status"] in ("IN_PRODUCTION", "COMPLETE"):
        fail("ERR_ORDER_IN_PRODUCTION",
             "an order IN_PRODUCTION or COMPLETE cannot be cancelled")
    if order["order_state"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "the order is already CANCELLED")
    if order["artwork_status"] == "ART_APPROVED":
        fee = int((Decimal(order["final_quote_cents"]) * CANCEL_FEE_RATE).quantize(
            Decimal("1"), rounding="ROUND_HALF_UP"))
    else:
        fee = 0
    if order["payment_status"] == "AUTHORIZED":
        refund = 0  # the authorization is simply voided
    elif order["payment_status"] == "CAPTURED":
        refund = max(0, order["final_quote_cents"] - fee)
    else:
        refund = 0  # UNPAID: no money moved, payment stays UNPAID
    order["cancellation_fee_cents"] = fee
    order["refund_cents"] += refund
    order["order_state"] = "CANCELLED"
    if order["payment_status"] in ("AUTHORIZED", "CAPTURED"):
        order["payment_status"] = "REFUNDED"
    # Release any live reservation and run the waitlist-promotion cascade.
    if order["reservation_status"] in ("HELD", "CONFIRMED", "WAITLISTED"):
        slot = DB.slots.get(order["slot_id"]) if order["slot_id"] else None
        order["reservation_status"] = "RELEASED"
        order["slot_id"] = None
        order["schedule_status"] = "UNSCHEDULED"
        if slot is not None:
            promote_waitlist(slot)
    touch(order)
    return success(ser_order(order))
