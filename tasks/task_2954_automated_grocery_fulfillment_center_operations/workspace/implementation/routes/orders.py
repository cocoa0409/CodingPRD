"""Baskets, order lines and cancellation (PRD 3.2, 3.6, 3.9)."""

from flask import Blueprint

import db as store
from db import db
from errors import ApiError
import response as resp
import validation as v
from middleware import endpoint, must_get, actor_id, require_ownership
from services import cascade, derive, money

bp = Blueprint("orders", __name__)

CUSTOMER = ["Customer"]
ORDER_READERS = ["FulfillmentAdmin", "WavePlanner", "PickOperator", "Customer"]
CANCELLABLE = ("DRAFT", "SLOTTED", "WAVED")


# --------------------------------------------------------------------------
# Baskets
# --------------------------------------------------------------------------
@bp.route("/customer-orders", methods=["POST"])
@endpoint(roles=CUSTOMER, mutating=True)
def create_order():
    data = v.check_body(v.read_body(), [
        v.f_dec("stop_distance_km", "0.01", "99.99", 2),
    ])
    order = store.insert(db.orders, {
        "customer_id": actor_id(),
        "wave_id": None,
        "stop_distance_km": data["stop_distance_km"],
        "fulfillment_status": "DRAFT",
        "billing_status": "PENDING_AUTH",
        "merchandise_subtotal_cents": 0,
        "delivery_fee_cents": None,
        "loyalty_discount_cents": None,
        "order_total_cents": None,
        "authorized_amount_cents": None,
        "captured_amount_cents": None,
        "dispatch_blocked": False,
        "open_substitution_count": 0,
    })
    return resp.created(order)


@bp.route("/customer-orders/<order_id>", methods=["GET"])
@endpoint(roles=ORDER_READERS)
def read_order(order_id):
    return resp.obj(must_get(db.orders, order_id, "ERR_ORDER_NOT_FOUND"))


@bp.route("/customer-orders", methods=["GET"])
@endpoint(roles=ORDER_READERS)
def list_orders():
    items = resp.filtered(list(db.orders.values()), {
        "customer_id": "customer_id",
        "wave_id": "wave_id",
        "fulfillment_status": "fulfillment_status",
    })
    return resp.listing(items)


@bp.route("/customer-orders/<order_id>/lines", methods=["POST"])
@endpoint(roles=CUSTOMER, mutating=True)
def add_line(order_id):
    order = must_get(db.orders, order_id, "ERR_ORDER_NOT_FOUND")
    body = v.read_body()
    sku = v.fk(body, "sku_id", db.skus, "ERR_SKU_NOT_FOUND")
    require_ownership(order)
    data = v.check_body(body, [
        v.f_id("sku_id"),
        v.f_int("ordered_qty", 1, 200),
    ])
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "lines may only be added to a DRAFT basket")

    line = store.insert(db.lines, {
        "order_id": order["id"],
        "sku_id": sku["id"],
        "ordered_qty": data["ordered_qty"],
        "line_status": "PENDING",
        "substitution_resolution": "NOT_REQUIRED",
        "nominal_weight_grams": (
            sku["nominal_weight_grams"] if sku["is_catchweight"] else None
        ),
        "provisional_line_price_cents": money.provisional_price(
            sku, data["ordered_qty"]
        ),
        "final_line_price_cents": None,
        "picked_units": None,
        "picked_weight_grams": None,
    })
    money.run_waterfall(order)
    store.bump(order)
    return resp.created(line)


@bp.route("/customer-orders/<order_id>/cancel", methods=["POST"])
@endpoint(roles=CUSTOMER, mutating=True)
def cancel(order_id):
    order = must_get(db.orders, order_id, "ERR_ORDER_NOT_FOUND")
    require_ownership(order)
    v.check_body(v.read_body(), [])
    if order["fulfillment_status"] not in CANCELLABLE:
        raise ApiError(
            "ERR_INVALID_STATE",
            "an order may only be cancelled from DRAFT, SLOTTED or WAVED",
        )
    if order["fulfillment_status"] == "WAVED":
        wave = derive.order_wave(order)
        if wave is None or wave["status"] != "FORMING":
            raise ApiError(
                "ERR_INVALID_STATE",
                "a waved order may only be cancelled while its wave is FORMING",
            )
    cascade.cancel_order(order)
    return resp.obj(order)


# --------------------------------------------------------------------------
# Order lines
# --------------------------------------------------------------------------
@bp.route("/order-lines/<line_id>", methods=["GET"])
@endpoint(roles=ORDER_READERS)
def read_line(line_id):
    return resp.obj(must_get(db.lines, line_id, "ERR_ORDER_LINE_NOT_FOUND"))


@bp.route("/order-lines", methods=["GET"])
@endpoint(roles=ORDER_READERS)
def list_lines():
    items = resp.filtered(list(db.lines.values()), {
        "order_id": "order_id",
        "sku_id": "sku_id",
        "line_status": "line_status",
    })
    return resp.listing(items)


@bp.route("/order-lines/<line_id>/accept-shortage", methods=["POST"])
@endpoint(roles=CUSTOMER, mutating=True)
def accept_shortage(line_id):
    line = must_get(db.lines, line_id, "ERR_ORDER_LINE_NOT_FOUND")
    order = db.orders[line["order_id"]]
    require_ownership(order)
    v.check_body(v.read_body(), [])
    if line["substitution_resolution"] != "PENDING":
        raise ApiError(
            "ERR_LINE_NOT_SHORT", "the line is not awaiting a substitution decision"
        )
    line["line_status"] = "CANCELLED"
    line["substitution_resolution"] = "SHORTAGE_ACCEPTED"
    for proposal in derive.line_proposals(line):
        if proposal["status"] in ("DRAFT", "PROPOSED"):
            proposal["status"] = "EXPIRED"
    derive.recompute_order_flags(order)
    money.run_waterfall(order)
    store.bump(order)
    return resp.obj(line)
