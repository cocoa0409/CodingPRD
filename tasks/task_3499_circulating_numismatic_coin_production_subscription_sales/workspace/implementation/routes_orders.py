"""Collector registration and the numismatic order flow: household limits,
the allocation waterfall, exact payment, cancellation with waitlist
promotion (PRD §3.6)."""
from flask import Blueprint, request

import serialize
import store
from helpers import (auth, body, envelope, err, list_response, need_int,
                     need_str, no_undeclared, not_found)
from routes_products import refresh_sale_status

bp = Blueprint("orders", __name__)


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------
@bp.route("/mint/collectors", methods=["POST"])
def register_collector():
    auth("Anonymous")
    b = body()
    no_undeclared(b, {"full_name", "email", "household_id"})
    name = need_str(b, "full_name")
    email = need_str(b, "email")
    household = need_str(b, "household_id")
    if any(c["email"] == email for c in store.db["collectors"].values()):
        err("ERR_EMAIL_EXISTS", 409, "email already registered")
    c = store.mint_entity({
        "full_name": name,
        "email": email,
        "household_id": household,
    })
    store.db["collectors"][c["id"]] = c
    return envelope(serialize.collector(c), status=201)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
def _household_units(product_id, household_id):
    """Sum of quantities over non-CANCELLED orders (allocation_status !=
    RELEASED) for this product by any collector sharing the household."""
    total = 0
    for o in store.db["orders"].values():
        if o["product_id"] != product_id or o["allocation_status"] == "RELEASED":
            continue
        c = store.db["collectors"].get(o["collector_id"])
        if c is not None and c["household_id"] == household_id:
            total += o["quantity"]
    return total


def _promote_waitlist(product):
    """Strict head-of-line promotion over WAITLISTED orders, oldest first by
    created_at with server receipt order breaking ties; the scan stops the
    moment the earliest waiting order does not fit."""
    while True:
        remaining = product["mintage_limit"] - serialize.allocated_units(product["id"])
        waiting = [o for o in store.db["orders"].values()
                   if o["product_id"] == product["id"]
                   and o["allocation_status"] == "WAITLISTED"]
        if not waiting:
            return
        waiting.sort(key=lambda o: (o["created_at"], o["_seq"]))
        head = waiting[0]
        if head["quantity"] > remaining:
            return
        head["allocation_status"] = "ALLOCATED"
        store.bump(head)
        refresh_sale_status(product)


@bp.route("/mint/orders", methods=["POST"])
def place_order():
    uid, _ = auth("Collector")
    b = body()
    # Body FK resolution, then the rung-5 product-state gate evaluates
    # against the resolved product (rung 5 surfaces before rung-9 shape).
    product = None
    if isinstance(b.get("product_id"), str):
        product = store.db["products"].get(b["product_id"])
        if product is None:
            err("ERR_UNKNOWN_PRODUCT", 422, "Unknown product_id")
    if product is not None and product["status"] not in ("ON_SALE", "SOLD_OUT"):
        err("ERR_PRODUCT_NOT_ORDERABLE", 422,
            "Orders may be placed only against ON_SALE or SOLD_OUT products")
    # Rung 9: shape.
    no_undeclared(b, {"product_id", "quantity"})
    if product is None:
        pid = need_str(b, "product_id")
        product = store.db["products"].get(pid)
        if product is None:
            err("ERR_UNKNOWN_PRODUCT", 422, "Unknown product_id")
        if product["status"] not in ("ON_SALE", "SOLD_OUT"):
            err("ERR_PRODUCT_NOT_ORDERABLE", 422,
                "Orders may be placed only against ON_SALE or SOLD_OUT products")
    qty = need_int(b, "quantity")
    if qty < 1:
        err("ERR_QUANTITY_INVALID", 400, "quantity must be at least 1")
    # Rung 10: household limit (equality allowed).
    collector = store.db["collectors"].get(uid)
    household_id = collector["household_id"] if collector is not None else None
    if household_id is not None:
        used = _household_units(product["id"], household_id)
        if used + qty > product["household_order_limit"]:
            err("ERR_HOUSEHOLD_LIMIT_EXCEEDED", 422,
                "Household order limit would be exceeded")
    # Allocation waterfall: whole order allocates or waitlists; partial
    # fills are never performed.
    alloc = serialize.allocated_units(product["id"])
    if alloc + qty <= product["mintage_limit"]:
        allocation_status = "ALLOCATED"
    else:
        allocation_status = "WAITLISTED"
    o = store.mint_entity({
        "collector_id": uid,
        "product_id": product["id"],
        "quantity": qty,
        "total_cents": qty * product["price_cents"],
        "payment_status": "UNPAID",
        "allocation_status": allocation_status,
    })
    store.db["orders"][o["id"]] = o
    if allocation_status == "ALLOCATED":
        refresh_sale_status(product)
    return envelope(serialize.order(o), status=201)


def _collector_scope_or_forbid(uid):
    """Collector list rule: a collector_id filter must name the caller's own
    id; results are scoped to the caller's own records."""
    filt = request.args.get("collector_id")
    if filt is not None and filt != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", 403,
            "Collector list filter must name the caller's own collector_id")
    return uid


@bp.route("/mint/orders", methods=["GET"])
def list_orders():
    uid, role = auth("Collector", "ProgramManager", "MintDirector", "PlatformAdmin")
    items = list(store.db["orders"].values())
    if role == "Collector":
        own = _collector_scope_or_forbid(uid)
        items = [o for o in items if o["collector_id"] == own]
    else:
        filt = request.args.get("collector_id")
        if filt is not None:
            items = [o for o in items if o["collector_id"] == filt]
    for param, field in (("product_id", "product_id"),
                         ("allocation_status", "allocation_status"),
                         ("payment_status", "payment_status")):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o[field] == v]
    return list_response(items, serialize.order)


def _get_order_or_404(oid):
    o = store.db["orders"].get(oid)
    if o is None:
        not_found("Order not found")
    return o


def _own_order_or_forbid(o, uid):
    if o["collector_id"] != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", 403, "Order belongs to another collector")


@bp.route("/mint/orders/<oid>", methods=["GET"])
def get_order(oid):
    uid, role = auth("Collector", "ProgramManager", "MintDirector", "PlatformAdmin")
    o = _get_order_or_404(oid)
    if role == "Collector":
        _own_order_or_forbid(o, uid)
    return envelope(serialize.order(o))


@bp.route("/mint/orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    uid, _ = auth("Collector")
    o = _get_order_or_404(oid)
    _own_order_or_forbid(o, uid)
    if o["payment_status"] != "UNPAID" or o["allocation_status"] != "ALLOCATED":
        err("ERR_ORDER_NOT_PAYABLE", 422,
            "Only an UNPAID, ALLOCATED order may be paid")
    b = body()
    no_undeclared(b, {"amount_cents"})
    amount = need_int(b, "amount_cents")
    if amount != o["total_cents"]:
        err("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
            "amount_cents must equal the order's total_cents exactly")
    o["payment_status"] = "PAID"
    store.bump(o)
    return envelope(serialize.order(o))


@bp.route("/mint/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    uid, _ = auth("Collector")
    o = _get_order_or_404(oid)
    _own_order_or_forbid(o, uid)
    if o["allocation_status"] == "RELEASED":
        err("ERR_ORDER_NOT_CANCELLABLE", 422, "Order is already released")
    no_undeclared(body(), set())
    was_allocated = o["allocation_status"] == "ALLOCATED"
    o["allocation_status"] = "RELEASED"
    if o["payment_status"] == "PAID":
        o["payment_status"] = "REFUNDED"
    store.bump(o)
    if was_allocated:
        product = store.db["products"].get(o["product_id"])
        if product is not None:
            # Reopen a sold-out product, then run waitlist promotion on the
            # released units.
            refresh_sale_status(product)
            _promote_waitlist(product)
    return envelope(serialize.order(o))
