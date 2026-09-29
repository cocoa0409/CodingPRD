"""In-stream carts, holds, abandonment, recovery, checkout and the order ledger
(PRD 3.6, 3.7)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serializers as ser
from envelope import respond, respond_list
from errors import ApiError
from guards import (
    ALL_ROLES, ROLE_COMPLIANCE, ROLE_MERCH, ROLE_ADMIN, ROLE_SHOW_PRODUCER,
    ROLE_VIEWER, authenticate, body, fk_id, get_cart, get_cart_item, get_offer,
    get_order, get_show, pagination, req_int, req_str, slice_rows,
)
from store import by_created, db, new_record, now, touch

bp = Blueprint("commerce", __name__)

CART_LIST_ROLES = [ROLE_SHOW_PRODUCER, ROLE_MERCH, ROLE_COMPLIANCE, ROLE_VIEWER, ROLE_ADMIN]


# --------------------------------------------------------------------- carts
@bp.post("/carts")
def create_cart():
    user_id, _ = authenticate([ROLE_VIEWER])
    payload = body()
    show = get_show(fk_id(payload, "show_id"))
    record = new_record()
    record.update({
        "show_id": show["id"],
        "viewer_id": user_id,
        "status": "OPEN",
        "bundle_discount_pct": 0.0,
        "abandoned_at": None,
        "recovery_deadline_at": None,
        "recovered_count": 0,
        "checked_out_at": None,
    })
    db.carts[record["id"]] = record
    return respond(ser.cart_out(record), 201)


@bp.get("/carts/<cart_id>")
def read_cart(cart_id):
    authenticate(ALL_ROLES)
    return respond(ser.cart_out(get_cart(cart_id)))


@bp.get("/carts")
def list_carts():
    authenticate(CART_LIST_ROLES)
    limit, offset = pagination()
    rows = list(db.carts.values())
    for field in ("show_id", "viewer_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = slice_rows(by_created(rows), limit, offset)
    return respond_list([ser.cart_out(r) for r in page], limit, offset, total)


@bp.post("/carts/<cart_id>/items")
def add_cart_item(cart_id):
    user_id, _ = authenticate([ROLE_VIEWER])
    cart = get_cart(cart_id)
    if cart["viewer_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    payload = body()
    offer = get_offer(fk_id(payload, "flash_offer_id"))
    qty = req_int(payload, "qty", 1, 20)
    if cart["status"] != "OPEN":
        raise ApiError("ERR_INVALID_CART_STATE")
    show = db.shows.get(cart["show_id"])
    if show is None or show["status"] != "LIVE":
        raise ApiError("ERR_INVALID_SHOW_STATE")
    if offer["status"] != "ACTIVE":
        raise ApiError("ERR_OFFER_NOT_ACTIVE")
    slot = calc.slot_of_offer(offer)
    product = db.products.get(slot["product_id"]) if slot is not None else None
    if product is None or product["claim_substantiation_status"] != "SUBSTANTIATED":
        raise ApiError("ERR_CLAIM_NOT_SUBSTANTIATED")
    stamp = now()
    if stamp < offer["window_start_at"] or stamp > offer["window_end_at"]:
        raise ApiError("ERR_OFFER_WINDOW_CLOSED")
    if slot["show_id"] != cart["show_id"]:
        raise ApiError("ERR_OFFER_SHOW_MISMATCH")
    held_lines = [i for i in calc.items_of_cart(cart["id"]) if i["state"] == "HELD"]
    if len(held_lines) >= calc.MAX_CART_DISTINCT_ITEMS:
        raise ApiError("ERR_CART_ITEM_LIMIT")
    if calc.offer_remaining(offer) < qty:
        raise ApiError("ERR_OFFER_QTY_EXCEEDED")
    if calc.product_available(product) < qty:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY")
    record = new_record()
    record.update({
        "cart_id": cart["id"],
        "flash_offer_id": offer["id"],
        "lineup_slot_id": slot["id"],
        "qty": qty,
        "list_unit_price_cents": product["base_price_cents"],
        "offer_unit_price_cents": offer["offer_price_cents"],
        "effective_unit_price_cents": 0,
        "line_gross_cents": 0,
        "line_tax_cents": 0,
        "state": "HELD",
        "released_reason": None,
        "released_at": None,
    })
    db.cart_items[record["id"]] = record
    # PRD 3.6 — the pinned four-step pricing order.
    subtotal = calc.held_subtotal(cart["id"])
    pct = calc.bundle_tier(subtotal)
    cart["bundle_discount_pct"] = float(pct)
    calc.lock_line_price(record, pct)
    touch(cart)
    calc.sync_offer_allotment(offer)
    return respond(ser.item_out(record), 201)


@bp.post("/carts/<cart_id>/abandon")
def abandon_cart(cart_id):
    user_id, role = authenticate([ROLE_VIEWER, ROLE_MERCH])
    cart = get_cart(cart_id)
    if role == ROLE_VIEWER and cart["viewer_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if cart["status"] != "OPEN":
        raise ApiError("ERR_INVALID_CART_STATE")
    stamp = now()
    released = []
    for item in by_created(calc.items_of_cart(cart["id"])):
        if item["state"] != "HELD":
            continue
        item["state"] = "RELEASED"
        item["released_reason"] = "CART_ABANDONED"
        item["released_at"] = stamp
        touch(item)
        released.append(item)
    calc.restock_offers_after_release(released)
    cart["status"] = "ABANDONED"
    cart["abandoned_at"] = stamp
    cart["recovery_deadline_at"] = stamp + timedelta(minutes=calc.RECOVERY_WINDOW_MIN)
    touch(cart)
    return respond(ser.cart_out(cart))


def _recoverable(item):
    """PRD 3.7: recoverable when the offer is ACTIVE, its remaining_qty is at
    least the line's qty, and the product's available_qty is at least the qty."""
    offer = db.offers.get(item["flash_offer_id"])
    if offer is None or offer["status"] != "ACTIVE":
        return False
    if calc.offer_remaining(offer) < item["qty"]:
        return False
    product = calc.product_of_item(item)
    if product is None or calc.product_available(product) < item["qty"]:
        return False
    return True


@bp.post("/carts/<cart_id>/recover")
def recover_cart(cart_id):
    user_id, role = authenticate([ROLE_VIEWER, ROLE_MERCH])
    cart = get_cart(cart_id)
    if role == ROLE_VIEWER and cart["viewer_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if cart["status"] != "ABANDONED":
        raise ApiError("ERR_INVALID_CART_STATE")
    deadline = cart["recovery_deadline_at"]
    if deadline is None or not now() < deadline:
        raise ApiError("ERR_RECOVERY_WINDOW_CLOSED")
    lines = [i for i in by_created(calc.items_of_cart(cart["id"])) if i["state"] == "RELEASED"]
    if not [i for i in lines if _recoverable(i)]:
        raise ApiError("ERR_NO_RECOVERABLE_ITEMS")
    pct = calc.bundle_tier(calc.held_subtotal(cart["id"]))
    for item in lines:
        # Eligibility is re-evaluated per line against the live ledgers.
        if not _recoverable(item):
            continue
        offer = db.offers.get(item["flash_offer_id"])
        item["state"] = "HELD"
        item["released_reason"] = None
        item["released_at"] = None
        pct = calc.bundle_tier(calc.held_subtotal(cart["id"]))
        calc.lock_line_price(item, pct)
        touch(item)
        calc.sync_offer_allotment(offer)
    cart["bundle_discount_pct"] = float(pct)
    cart["status"] = "OPEN"
    cart["recovered_count"] += 1
    cart["abandoned_at"] = None
    cart["recovery_deadline_at"] = None
    touch(cart)
    return respond(ser.cart_out(cart))


@bp.post("/carts/<cart_id>/checkout")
def checkout_cart(cart_id):
    user_id, _ = authenticate([ROLE_VIEWER])
    cart = get_cart(cart_id)
    if cart["viewer_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    payload = body()
    expected_version = req_int(payload, "expected_cart_version")
    if expected_version != cart["version"]:
        raise ApiError("ERR_STALE_CART_VERSION")
    if cart["status"] != "OPEN":
        raise ApiError("ERR_INVALID_CART_STATE")
    show = db.shows.get(cart["show_id"])
    if show is None or show["status"] != "LIVE":
        raise ApiError("ERR_INVALID_SHOW_STATE")
    held_lines = [i for i in by_created(calc.items_of_cart(cart["id"])) if i["state"] == "HELD"]
    if not held_lines:
        raise ApiError("ERR_EMPTY_CART")
    stamp = now()
    for item in held_lines:
        item["state"] = "COMMITTED"
        touch(item)
    cart["status"] = "CHECKED_OUT"
    cart["checked_out_at"] = stamp
    touch(cart)
    merchandise, tax, shipping, total = calc.order_totals(held_lines)
    order = new_record()
    order.update({
        "cart_id": cart["id"],
        "show_id": cart["show_id"],
        "viewer_id": cart["viewer_id"],
        "payment_state": "AUTHORIZED",
        "fulfillment_state": "PENDING",
        "merchandise_cents": merchandise,
        "tax_cents": tax,
        "shipping_cents": shipping,
        "total_cents": total,
        "host_commission_accrued_cents": 0,
        "refunded_cents": 0,
        "captured_at": None,
        "cancelled_at": None,
        "cancel_reason": None,
    })
    db.orders[order["id"]] = order
    return respond(ser.order_out(order), 201)


# ----------------------------------------------------------------- cart lines
@bp.get("/cart-items/<item_id>")
def read_cart_item(item_id):
    authenticate(ALL_ROLES)
    return respond(ser.item_out(get_cart_item(item_id)))


@bp.get("/cart-items")
def list_cart_items():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.cart_items.values())
    for field in ("cart_id", "flash_offer_id", "lineup_slot_id", "state"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = slice_rows(by_created(rows), limit, offset)
    return respond_list([ser.item_out(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------- orders
@bp.get("/orders/<order_id>")
def read_order(order_id):
    authenticate(ALL_ROLES)
    return respond(ser.order_out(get_order(order_id)))


@bp.get("/orders")
def list_orders():
    authenticate(CART_LIST_ROLES)
    limit, offset = pagination()
    rows = list(db.orders.values())
    for field in ("cart_id", "show_id", "viewer_id", "payment_state"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = slice_rows(by_created(rows), limit, offset)
    return respond_list([ser.order_out(r) for r in page], limit, offset, total)


@bp.post("/orders/<order_id>/capture")
def capture_order(order_id):
    authenticate([ROLE_MERCH])
    order = get_order(order_id)
    if order["payment_state"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    show = db.shows.get(order["show_id"])
    if show is None or show["status"] not in ("LIVE", "ENDED"):
        raise ApiError("ERR_INVALID_SHOW_STATE")
    host = calc.primary_host(order["show_id"])
    pct = calc.dec(host["commission_pct"]) if host is not None else calc.dec(0)
    order["payment_state"] = "CAPTURED"
    order["captured_at"] = now()
    order["fulfillment_state"] = "ALLOCATED"
    order["host_commission_accrued_cents"] = calc.rhu(calc.dec(order["merchandise_cents"]) * pct)
    touch(order)
    calc.stamp_provisional_margin(show)
    return respond(ser.order_out(order))


@bp.post("/orders/<order_id>/cancel")
def cancel_order(order_id):
    user_id, role = authenticate([ROLE_MERCH, ROLE_VIEWER])
    order = get_order(order_id)
    if role == ROLE_VIEWER and order["viewer_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    payload = body()
    cancel_reason = req_str(payload, "cancel_reason")
    if order["payment_state"] not in ("AUTHORIZED", "CAPTURED"):
        raise ApiError("ERR_INVALID_ORDER_STATE")
    was_captured = order["payment_state"] == "CAPTURED"
    stamp = now()
    order["cancelled_at"] = stamp
    order["cancel_reason"] = cancel_reason
    order["fulfillment_state"] = "CANCELLED"
    released = []
    for item in by_created(calc.items_of_cart(order["cart_id"])):
        if item["state"] != "COMMITTED":
            continue
        item["state"] = "RELEASED"
        item["released_reason"] = "ORDER_CANCELLED"
        item["released_at"] = stamp
        touch(item)
        released.append(item)
    calc.restock_offers_after_release(released)
    if was_captured:
        order["payment_state"] = "REFUNDED"
        order["refunded_cents"] = order["total_cents"]
        order["host_commission_accrued_cents"] = 0
    else:
        order["payment_state"] = "VOIDED"
    touch(order)
    show = db.shows.get(order["show_id"])
    if was_captured and show is not None:
        calc.stamp_provisional_margin(show)
    return respond(ser.order_out(order))
