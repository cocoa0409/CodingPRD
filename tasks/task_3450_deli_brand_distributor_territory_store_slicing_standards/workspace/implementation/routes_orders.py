"""Order and OrderLine endpoints, weekly allocation, cancellation (PRD SS3.3)."""
from flask import Blueprint, request

import store
from domain import allocate_week, cancel_order, order_lines
from errors import fail
from serializers import ser_order, ser_order_line
from store import db
from util import (auth, body, list_response, new_id, ok, ok_array, req_array,
                  req_date, req_int, req_str, sort_std)

bp = Blueprint("orders", __name__)

ORDER_READERS = ("BrandAdmin", "DistributorRep", "PlantScheduler")


def _get_order(oid):
    o = db["orders"].get(oid)
    if o is None:
        fail("ERR_NOT_FOUND", 404, "order not found")
    return o


@bp.post("/api/orders")
def create_order():
    _, uid = auth("DistributorRep")
    b = body()
    delivery_week = req_date(b, "delivery_week")
    lines_in = req_array(b, "lines", non_empty=True)
    parsed = []
    for item in lines_in:
        if not isinstance(item, dict):
            fail("ERR_VALIDATION", 400, "each order line must be an object")
        pid = req_str(item, "product_id")
        qty = req_int(item, "qty_requested", min_value=1)
        parsed.append((pid, qty))
    # referenced-resource existence, left to right
    products = []
    for pid, _qty in parsed:
        p = db["products"].get(pid)
        if p is None:
            fail("ERR_NOT_FOUND", 404, "product not found")
        products.append(p)
    # standing gate: the acting distributor must be ACTIVE
    dist = db["distributors"].get(uid)
    if dist is None:
        fail("ERR_NOT_FOUND", 404, "distributor not found")
    if dist["status"] != "ACTIVE":
        fail("ERR_DISTRIBUTOR_NOT_ACTIVE", 409, "distributor is not ACTIVE")
    now = store.now()
    order = {
        "id": new_id(), "_seq": store.next_seq(), "distributor_id": uid,
        "delivery_week": delivery_week,
        "allocation_status": "PENDING", "fulfillment_status": "UNSHIPPED",
        "merchandise_total_cents": 0, "discount_cents": 0,
        "delivery_fee_cents": 0, "total_cents": 0,
        "created_at": now, "updated_at": now, "version": 1,
    }
    db["orders"][order["id"]] = order
    for (pid, qty), p in zip(parsed, products):
        # unit price snapshots from the product's current base price
        line = {
            "id": new_id(), "_seq": store.next_seq(), "order_id": order["id"],
            "product_id": pid, "qty_requested": qty, "qty_allocated": 0,
            "unit_price_cents": p["base_price_cents"], "line_total_cents": 0,
            "created_at": now,
        }
        db["order_lines"][line["id"]] = line
    return ok(ser_order(order), 201)


@bp.get("/api/orders")
def list_orders():
    auth(*ORDER_READERS)
    items = sort_std(db["orders"].values())
    distributor_id = request.args.get("distributor_id")
    delivery_week = request.args.get("delivery_week")
    allocation = request.args.get("allocation_status")
    fulfillment = request.args.get("fulfillment_status")
    if distributor_id is not None:
        items = [o for o in items if o["distributor_id"] == distributor_id]
    if delivery_week is not None:
        items = [o for o in items if o["delivery_week"] == delivery_week]
    if allocation is not None:
        items = [o for o in items if o["allocation_status"] == allocation]
    if fulfillment is not None:
        items = [o for o in items if o["fulfillment_status"] == fulfillment]
    return list_response([ser_order(o) for o in items])


@bp.get("/api/orders/<oid>")
def get_order(oid):
    auth(*ORDER_READERS)
    return ok(ser_order(_get_order(oid)))


@bp.get("/api/order-lines")
def list_order_lines():
    auth(*ORDER_READERS)
    items = sort_std(db["order_lines"].values())
    order_id = request.args.get("order_id")
    product_id = request.args.get("product_id")
    if order_id is not None:
        items = [l for l in items if l["order_id"] == order_id]
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    return list_response([ser_order_line(l) for l in items])


@bp.get("/api/order-lines/<lid>")
def get_order_line(lid):
    auth(*ORDER_READERS)
    l = db["order_lines"].get(lid)
    if l is None:
        fail("ERR_NOT_FOUND", 404, "order line not found")
    return ok(ser_order_line(l))


@bp.post("/api/orders/allocate-week")
def allocate_week_endpoint():
    auth("PlantScheduler")
    b = body()
    delivery_week = req_date(b, "delivery_week")
    processed = allocate_week(delivery_week)
    return ok_array([ser_order(o) for o in processed])


@bp.post("/api/orders/<oid>/cancel")
def cancel_order_endpoint(oid):
    _, uid = auth("DistributorRep")
    o = _get_order(oid)
    # entity-backed ownership: the acting rep must own the order
    if o["distributor_id"] != uid:
        fail("ERR_FORBIDDEN", 403, "X-User-ID must equal the order's distributor_id")
    if o["allocation_status"] == "CANCELLED" or o["fulfillment_status"] in ("DELIVERED", "REJECTED"):
        fail("ERR_ALREADY_TERMINAL", 409, "order is in a terminal state")
    if o["fulfillment_status"] != "UNSHIPPED":
        fail("ERR_INVALID_STATE", 409, "order has already shipped")
    cancel_order(o)
    return ok(ser_order(o))
