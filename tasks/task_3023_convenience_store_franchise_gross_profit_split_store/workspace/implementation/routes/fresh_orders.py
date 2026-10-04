"""FreshOrder routes — booking, delivery, reconciliation and cancellation."""

from datetime import timedelta

from flask import Blueprint, request

import db
import middleware
import schemas
import services
import timeutil
from errors import fail
from response import ok
from routes.common import SHARED, list_records

bp = Blueprint("fresh_orders", __name__)


def _recompute_waste_for_store(store_id, window):
    """Refresh the waste charge of any in-flight settlement covering the window."""
    for settlement in db.all_of("settlements"):
        if settlement["store_id"] != store_id:
            continue
        if settlement["status"] not in ("DRAW_PAID", "RECONCILED", "DISPUTED"):
            continue
        if not timeutil.overlaps(window["window_start"], window["window_end"],
                                 settlement["period_start"], settlement["period_end"]):
            continue
        services.recompute_settlement_waste(settlement)
        services.recalculate_settlement_net(settlement)
        db.touch(settlement)


@bp.post("/fresh-orders")
@middleware.auth(("Franchisee",))
def create_order():
    payload = middleware.body(
        required=("store_id", "delivery_window_id", "sku_code", "ordered_units",
                  "unit_cost_cents"),
    )
    store = services.require_store(payload["store_id"])
    window = services.require("delivery_windows", payload["delivery_window_id"])
    sku_code = middleware.string_value(payload["sku_code"], "sku_code")
    ordered_units = middleware.positive_int(payload["ordered_units"], "ordered_units")
    unit_cost = middleware.non_negative_int(payload["unit_cost_cents"], "unit_cost_cents")

    if window["store_id"] != store["id"]:
        fail("ERR_RESOURCE_NOT_FOUND")
    if not store["cold_chain_certified"]:
        fail("ERR_COLD_CHAIN_BROKEN")
    if window["status"] != "SCHEDULED":
        fail("ERR_WINDOW_LOCKED")
    if int(window["reserved_units"]) + ordered_units > int(window["capacity_units"]):
        fail("ERR_WINDOW_CAPACITY_EXCEEDED")

    record = db.insert("fresh_orders", {
        "store_id": store["id"],
        "delivery_window_id": window["id"],
        "sku_code": sku_code,
        "ordered_units": ordered_units,
        "delivered_units": None,
        "waste_units": None,
        "unit_cost_cents": unit_cost,
        "line_waste_cents": None,
        "waste_share_cents": None,
        "status": "PLACED",
    })
    window["reserved_units"] = int(window["reserved_units"]) + ordered_units
    db.touch(window)
    return ok(schemas.dump("fresh_orders", record), 201)


@bp.get("/fresh-orders")
@middleware.auth(SHARED)
def list_orders():
    return list_records("fresh_orders", ("store_id", "delivery_window_id", "status"))


@bp.get("/fresh-orders/<order_id>")
@middleware.auth(SHARED)
def get_order(order_id):
    order = services.require("fresh_orders", order_id)
    return ok(schemas.dump("fresh_orders", order))


@bp.post("/fresh-orders/<order_id>/confirm")
@middleware.auth(("Commissary",))
def confirm_order(order_id):
    order = services.require("fresh_orders", order_id)
    services.require_state(order, "PLACED")
    window = services.require("delivery_windows", order["delivery_window_id"])
    if window["status"] != "SCHEDULED":
        fail("ERR_WINDOW_LOCKED")
    order["status"] = "CONFIRMED"
    db.touch(order)
    return ok(schemas.dump("fresh_orders", order))


@bp.post("/fresh-orders/<order_id>/deliver")
@middleware.auth(("Commissary",))
def deliver_order(order_id):
    order = services.require("fresh_orders", order_id)
    services.require_state(order, "CONFIRMED")
    payload = middleware.body(required=("delivered_units",))
    delivered_units = middleware.non_negative_int(payload["delivered_units"], "delivered_units")
    window = services.require("delivery_windows", order["delivery_window_id"])
    if window["status"] != "LOCKED":
        fail("ERR_WINDOW_NOT_LOCKED")
    clock = db.clock()
    if not (window["window_start"] <= clock < window["window_end"]):
        fail("ERR_DELIVERY_OUTSIDE_WINDOW")
    order["delivered_units"] = delivered_units
    order["status"] = "DELIVERED"
    db.touch(order)
    return ok(schemas.dump("fresh_orders", order))


@bp.post("/fresh-orders/<order_id>/reconcile")
@middleware.auth(("FranchisorAdmin",))
def reconcile_order(order_id):
    order = services.require("fresh_orders", order_id)
    services.require_state(order, "DELIVERED")
    payload = middleware.body(required=("waste_units",))
    waste_units = middleware.non_negative_int(payload["waste_units"], "waste_units")
    if waste_units > int(order["delivered_units"]):
        fail("ERR_INVALID_REQUEST")

    order["waste_units"] = waste_units
    order["status"] = "RECONCILED"
    db.touch(order)

    window = services.require("delivery_windows", order["delivery_window_id"])
    window["reserved_units"] = max(0, int(window["reserved_units"]) - int(order["ordered_units"]))
    db.touch(window)

    services.apply_waste_share(order["store_id"], window)
    return ok(schemas.dump("fresh_orders", order))


@bp.post("/fresh-orders/<order_id>/cancel")
@middleware.auth(("Franchisee",))
def cancel_order(order_id):
    order = services.require("fresh_orders", order_id)
    identity = getattr(request, "acting_identity", None)
    owning = services._store_owner(order["store_id"])
    if identity != owning:
        fail("ERR_NOT_RESOURCE_OWNER")

    if order["status"] not in ("PLACED", "CONFIRMED"):
        fail("ERR_INVALID_STATE")

    window = services.require("delivery_windows", order["delivery_window_id"])
    clock = db.clock()
    if order["status"] == "PLACED":
        if not clock < window["window_start"] - timedelta(hours=24):
            fail("ERR_ORDER_CANCEL_WINDOW_CLOSED")
    else:
        if not clock < window["window_start"]:
            fail("ERR_ORDER_CANCEL_WINDOW_CLOSED")

    order["status"] = "CANCELLED"
    db.touch(order)
    window["reserved_units"] = max(0, int(window["reserved_units"]) - int(order["ordered_units"]))
    db.touch(window)

    for settlement in db.find("settlements", store_id=order["store_id"]):
        if settlement["status"] in ("OPEN", "DRAW_PAID"):
            services.finalize_settlement(settlement)
    return ok(schemas.dump("fresh_orders", order))