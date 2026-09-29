"""Pre-orders and the pick-up-on-return programme (PRD section 3.8)."""
from datetime import timedelta

from flask import Blueprint, g

import clock
import db
import response
from errors import ApiError
from middleware import actor, body, endpoint
from services import ledger
from services.lookup import fetch, fetch_body, listing
from services.scope import ALL_ROLES, ensure_owner, owned_predicate
from services.validate import req_enum, req_int, req_ts

from routes.sales import new_line, new_sale

bp = Blueprint("preorders", __name__)

PROGRAMS = ("PICKUP_ON_DEPARTURE", "PICKUP_ON_RETURN")
CAPACITY_BUFFER_HOURS = 24


@bp.post("/pre-orders")
@endpoint("Passenger")
def create_pre_order():
    payload = body()
    # tier 3: a passenger may only reserve against their own itinerary
    if payload.get("itinerary_id") != g.user_id:
        raise ApiError("ERR_NOT_ITINERARY_OWNER")
    item = fetch_body("stock_items", "stock_item_id", payload)
    itinerary = fetch_body("itineraries", "itinerary_id", payload)
    qty = req_int(payload, "qty", minimum=1)
    program = req_enum(payload, "program", PROGRAMS)
    window_start = req_ts(payload, "reservation_window_start")
    window_end = req_ts(payload, "reservation_window_end")
    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "reservation_window_end must be strictly later than reservation_window_start.",
        )
    expected_version = req_int(payload, "expected_stock_item_version")
    product = db.products[item["product_id"]]
    if product["assortment_status"] != "LISTED":
        raise ApiError("ERR_PRODUCT_NOT_LISTED")
    if expected_version != item["version"]:
        raise ApiError("ERR_STALE_STOCK_ITEM_VERSION")
    if item["terminal_id"] != itinerary["departure_terminal_id"]:
        raise ApiError("ERR_TERMINAL_MISMATCH")
    departure = clock.parse(itinerary["departure_utc"])
    if window_start < clock.now():
        raise ApiError("ERR_RESERVATION_WINDOW_INVALID",
                       "reservation_window_start may not lie in the logical past.")
    if program == "PICKUP_ON_DEPARTURE" and window_end > departure:
        raise ApiError("ERR_RESERVATION_WINDOW_INVALID",
                       "A PICKUP_ON_DEPARTURE window must close at or before departure.")
    if program == "PICKUP_ON_RETURN" and window_start < departure:
        raise ApiError("ERR_RESERVATION_WINDOW_INVALID",
                       "A PICKUP_ON_RETURN window must open at or after departure.")
    buffer = timedelta(hours=CAPACITY_BUFFER_HOURS)
    conflicting = 0
    for other in db.ordered(db.pre_orders,
                            lambda p: p["stock_item_id"] == item["id"]
                            and p["status"] == "RESERVED"):
        other_start = clock.parse(other["reservation_window_start"])
        other_end = clock.parse(other["reservation_window_end"])
        if other_start <= window_end + buffer and other_end >= window_start - buffer:
            conflicting += other["qty"]
    if conflicting + qty > item["on_hand_qty"]:
        raise ApiError("ERR_RESERVATION_CAPACITY_OVERLAP")
    pre_order = db.base()
    pre_order.update({
        "itinerary_id": itinerary["id"],
        "stock_item_id": item["id"],
        "qty": qty,
        "program": program,
        "reservation_window_start": clock.fmt(window_start),
        "reservation_window_end": clock.fmt(window_end),
        "status": "RESERVED",
        "converted_sale_id": None,
        "closed_at": None,
    })
    db.pre_orders[pre_order["id"]] = pre_order
    ledger.append(item, "RESERVATION_HOLD", qty, "PRE_ORDER", pre_order["id"], actor())
    return response.created(db.public(pre_order))


@bp.get("/pre-orders/<pre_order_id>")
@endpoint(*ALL_ROLES)
def get_pre_order(pre_order_id):
    pre_order = fetch("pre_orders", pre_order_id)
    ensure_owner(pre_order["itinerary_id"])
    return response.single(db.public(pre_order))


@bp.get("/pre-orders")
@endpoint(*ALL_ROLES)
def list_pre_orders():
    rows, limit, offset, total = listing(
        db.pre_orders,
        ("itinerary_id", "stock_item_id", "converted_sale_id", "program", "status"),
        owned_predicate(lambda p: p["itinerary_id"]),
    )
    return response.collection(rows, limit, offset, total)


@bp.post("/pre-orders/<pre_order_id>/convert")
@endpoint("StockController")
def convert_pre_order(pre_order_id):
    pre_order = fetch("pre_orders", pre_order_id)
    if pre_order["status"] != "RESERVED":
        raise ApiError("ERR_PREORDER_NOT_RESERVED")
    itinerary = db.itineraries[pre_order["itinerary_id"]]
    if itinerary["scan_status"] not in ("SCANNED", "AMENDED"):
        raise ApiError("ERR_ITINERARY_NOT_SCANNED")
    item = db.stock_items[pre_order["stock_item_id"]]
    terminal = db.terminals[item["terminal_id"]]
    agreement = ledger.active_agreement(terminal["id"])
    if agreement is None:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    product = db.products[item["product_id"]]
    if product["assortment_status"] != "LISTED":
        raise ApiError("ERR_PRODUCT_NOT_LISTED")
    now = clock.now()
    if not (clock.parse(pre_order["reservation_window_start"]) <= now
            <= clock.parse(pre_order["reservation_window_end"])):
        raise ApiError("ERR_RESERVATION_WINDOW_INVALID",
                       "The logical clock is outside the collection window.")
    sale = new_sale(itinerary, terminal, agreement, "PRE_ORDER")
    line = new_line(sale, product, pre_order["qty"])
    sale["gross_amount_cents"] = line["line_total_cents"]
    ledger.append(item, "RESERVATION_RELEASE", -pre_order["qty"], "PRE_ORDER",
                  pre_order["id"], actor())
    pre_order["status"] = "CONVERTED"
    pre_order["converted_sale_id"] = sale["id"]
    pre_order["closed_at"] = clock.now_iso()
    db.touch(pre_order)
    return response.single(db.public(pre_order))


@bp.post("/pre-orders/<pre_order_id>/cancel")
@endpoint("Passenger")
def cancel_pre_order(pre_order_id):
    pre_order = fetch("pre_orders", pre_order_id)
    ensure_owner(pre_order["itinerary_id"])
    if pre_order["status"] != "RESERVED":
        raise ApiError("ERR_PREORDER_NOT_RESERVED")
    item = db.stock_items[pre_order["stock_item_id"]]
    pre_order["status"] = "CANCELLED"
    pre_order["closed_at"] = clock.now_iso()
    db.touch(pre_order)
    ledger.append(item, "RESERVATION_RELEASE", -pre_order["qty"], "PRE_ORDER",
                  pre_order["id"], actor())
    return response.single(db.public(pre_order))
