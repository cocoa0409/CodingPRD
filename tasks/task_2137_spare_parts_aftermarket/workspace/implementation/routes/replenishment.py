"""Replenishment orders and their two independent status dimensions."""
from flask import Blueprint

import auth
import calc
import domain
import envelope
import serializers
import store
from errors import ApiError
from routes.registry import fk

bp = Blueprint("replenishment", __name__)

ORDER_TYPES = {"STOCK", "EMERGENCY_AIR"}
APPROVAL_STATUSES = {"PENDING", "APPROVED", "REJECTED"}
LOGISTICS_STATUSES = {"NOT_STARTED", "IN_TRANSIT", "RECEIVED"}


@bp.post("/aftermarket/replenishment-orders")
def create_order():
    auth.require("InventoryController")
    data = auth.body()
    part = fk(data, "part_id", domain.get_part)
    part_id = auth.req_id(data, "part_id")
    if part is None:
        part = domain.get_part(part_id)
    order_type = auth.req_enum(data, "order_type", ORDER_TYPES)
    qty = auth.req_int(data, "qty", minimum=1)

    # priority 11 — dangerous goods may not fly
    if order_type == "EMERGENCY_AIR" and part["hazmat"]:
        raise ApiError("ERR_HAZMAT_AIR_PROHIBITED")
    # priority 12 — a superseded part cannot be replenished
    if part["lifecycle_state"] == "SUPERSEDED":
        raise ApiError("ERR_PART_SUPERSEDED")
    # priority 28 — expediting must be justified by the stock position
    if (order_type == "EMERGENCY_AIR"
            and domain.replenishment_status(part) != "BELOW_REORDER_POINT"):
        raise ApiError("ERR_AIR_FREIGHT_NOT_JUSTIFIED")

    if order_type == "EMERGENCY_AIR":
        freight = calc.air_freight_cost(part["weight_kg"], qty, part["hazmat"])
    else:
        freight = 0

    rec = store.new_record("ReplenishmentOrder", {
        "part_id": part["id"],
        "order_type": order_type,
        "qty": qty,
        "unit_cost_cents": part["unit_cost_cents"],
        "freight_cost_cents": freight,
        "total_landed_cost_cents": part["unit_cost_cents"] * qty + freight,
        "approval_status": "PENDING",
        "logistics_status": "NOT_STARTED",
        "auto_generated": False,
        "rejection_reason": None,
    })
    store.replenishment_orders[rec["id"]] = rec
    return envelope.created(serializers.replenishment_order(rec))


@bp.get("/aftermarket/replenishment-orders/<order_id>")
def read_order(order_id):
    auth.require("InventoryController", "AftermarketPlanner", "PlatformAdmin")
    return envelope.ok(serializers.replenishment_order(domain.get_replenishment_order(order_id)))


@bp.get("/aftermarket/replenishment-orders")
def list_orders():
    auth.require("InventoryController", "AftermarketPlanner", "PlatformAdmin")
    limit, offset = auth.pagination()
    part_id = auth.query_str("part_id")
    order_type = auth.query_enum("order_type", ORDER_TYPES)
    approval_status = auth.query_enum("approval_status", APPROVAL_STATUSES)
    logistics_status = auth.query_enum("logistics_status", LOGISTICS_STATUSES)
    auto_generated = auth.query_bool("auto_generated")

    rows = list(store.replenishment_orders.values())
    if part_id is not None:
        rows = [r for r in rows if r["part_id"] == part_id]
    if order_type is not None:
        rows = [r for r in rows if r["order_type"] == order_type]
    if approval_status is not None:
        rows = [r for r in rows if r["approval_status"] == approval_status]
    if logistics_status is not None:
        rows = [r for r in rows if r["logistics_status"] == logistics_status]
    if auto_generated is not None:
        rows = [r for r in rows if r["auto_generated"] == auto_generated]
    rows = store.sort_created(rows)
    page, total = auth.paginate(rows, limit, offset)
    return envelope.listing([serializers.replenishment_order(r) for r in page],
                            limit, offset, total)


@bp.post("/aftermarket/replenishment-orders/<order_id>/approve")
def approve_order(order_id):
    auth.require("InventoryController")
    order = domain.get_replenishment_order(order_id)
    if order["approval_status"] != "PENDING":
        raise ApiError("ERR_REPLENISHMENT_STATE_INVALID")
    part = store.parts.get(order["part_id"])
    if part is not None and part["lifecycle_state"] == "OBSOLETE":
        raise ApiError("ERR_PART_LIFECYCLE_INVALID")

    order["approval_status"] = "APPROVED"
    store.touch(order)
    return envelope.ok(serializers.replenishment_order(order))


@bp.post("/aftermarket/replenishment-orders/<order_id>/reject")
def reject_order(order_id):
    auth.require("InventoryController")
    order = domain.get_replenishment_order(order_id)
    data = auth.body()
    rejection_reason = auth.opt_str(data, "rejection_reason")

    if order["approval_status"] != "PENDING":
        raise ApiError("ERR_REPLENISHMENT_STATE_INVALID")
    if order["logistics_status"] != "NOT_STARTED":
        raise ApiError("ERR_REPLENISHMENT_STATE_INVALID")

    order["approval_status"] = "REJECTED"
    order["rejection_reason"] = rejection_reason
    store.touch(order)
    return envelope.ok(serializers.replenishment_order(order))


@bp.post("/aftermarket/replenishment-orders/<order_id>/ship")
def ship_order(order_id):
    auth.require("InventoryController")
    order = domain.get_replenishment_order(order_id)
    if order["logistics_status"] != "NOT_STARTED":
        raise ApiError("ERR_REPLENISHMENT_STATE_INVALID")
    if order["approval_status"] != "APPROVED":
        raise ApiError("ERR_REPLENISHMENT_STATE_INVALID")

    order["logistics_status"] = "IN_TRANSIT"
    store.touch(order)

    part = store.parts.get(order["part_id"])
    if part is not None:
        part["in_transit_units"] += order["qty"]
        store.touch(part)
    return envelope.ok(serializers.replenishment_order(order))


@bp.post("/aftermarket/replenishment-orders/<order_id>/receive")
def receive_order(order_id):
    auth.require("InventoryController")
    order = domain.get_replenishment_order(order_id)
    if order["logistics_status"] != "IN_TRANSIT":
        raise ApiError("ERR_REPLENISHMENT_STATE_INVALID")
    part = store.parts.get(order["part_id"])
    if part is not None and part["lifecycle_state"] == "OBSOLETE":
        raise ApiError("ERR_PART_LIFECYCLE_INVALID")

    order["logistics_status"] = "RECEIVED"
    store.touch(order)

    if part is not None:
        part["in_transit_units"] -= order["qty"]
        part["on_hand_units"] += order["qty"]
        domain.append_ledger(part, "RECEIPT", order["qty"],
                             "REPLENISHMENT_ORDER", order["id"])
        domain.promote_backorders(part)
        store.touch(part)

    return envelope.ok(serializers.replenishment_order(order))
