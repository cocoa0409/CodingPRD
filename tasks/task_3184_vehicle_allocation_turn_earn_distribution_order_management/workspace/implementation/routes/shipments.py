"""Carriers and shipments (PRD §3.8)."""
from flask import Blueprint, request

import errors as err
from db import get_store, now_iso
from middleware import auth_context
from response import success_list, success_object
from services.core import recompute_dml
from util import (bump, current_iso_week, current_week_monday, new_entity,
                  req_int, req_str, req_week, week_monday)

bp = Blueprint("shipments", __name__)

LOGIS_ONLY = ["LogisticsCoordinator"]
CARRIER_READ = ["RegionalAllocator", "ProductionScheduler", "LogisticsCoordinator"]
SHIPMENT_READ = ["RegionalAllocator", "Dealer", "ProductionScheduler",
                 "LogisticsCoordinator"]


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


# ---------------------------------------------------------------------------
# Carriers (PRD §3.8)
# ---------------------------------------------------------------------------

@bp.post("/wholesale/carriers")
def create_carrier():
    auth_context(LOGIS_ONLY)
    body = _body()
    code = req_str(body, "code")
    name = req_str(body, "name")
    weekly_capacity = req_int(body, "weekly_capacity", 1)
    for c in get_store("carriers").values():
        if c["code"] == code:
            raise err.duplicate("carrier code already exists")
    carrier = new_entity({
        "code": code,
        "name": name,
        "weekly_capacity": weekly_capacity,
        "status": "ACTIVE",
    })
    get_store("carriers")[carrier["id"]] = carrier
    return success_object(carrier, 201)


@bp.get("/wholesale/carriers")
def list_carriers():
    auth_context(CARRIER_READ)
    rows = list(get_store("carriers").values())
    if request.args.get("status"):
        rows = [r for r in rows if r["status"] == request.args["status"]]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


@bp.get("/wholesale/carriers/<cid>")
def get_carrier(cid):
    auth_context(CARRIER_READ)
    carrier = get_store("carriers").get(cid)
    if carrier is None:
        raise err.not_found("carrier not found")
    return success_object(carrier)


# ---------------------------------------------------------------------------
# Shipments (PRD §3.8)
# ---------------------------------------------------------------------------

@bp.post("/wholesale/shipments")
def create_shipment():
    auth_context(LOGIS_ONLY)
    body = _body()
    order_id = req_str(body, "order_id")
    carrier_id = req_str(body, "carrier_id")
    pickup_week = req_week(body, "pickup_week")

    order = get_store("vehicle_orders").get(order_id)
    if order is None:
        raise err.not_found("order not found")
    carrier = get_store("carriers").get(carrier_id)
    if carrier is None:
        raise err.not_found("carrier not found")

    # Priority 5: order must be BUILT (shipment create exists only from BUILT).
    if order["state"] != "BUILT":
        raise err.invalid_state("order is not BUILT")

    # Priority 6: carrier must be ACTIVE.
    if carrier["status"] != "ACTIVE":
        raise err.parent_not_active("carrier is not ACTIVE")

    # Priority 11: temporal pickup-week gates.
    if order.get("scheduled_week") and week_monday(pickup_week) < week_monday(order["scheduled_week"]):
        raise err.pickup_before_build_week()
    if week_monday(pickup_week) < current_week_monday():
        raise err.window_closed("pickup_week earlier than current week")

    # Priority 16: at most one non-CANCELLED shipment per order.
    for s in get_store("shipments").values():
        if s["order_id"] == order_id and s["state"] != "CANCELLED":
            raise err.duplicate("order already has a non-CANCELLED shipment")

    # Carrier capacity: strict < (PRD §3.8).
    count = sum(
        1 for s in get_store("shipments").values()
        if s["carrier_id"] == carrier_id
        and s["pickup_week"] == pickup_week
        and s["state"] in ("PLANNED", "PICKED_UP")
    )
    if count >= carrier["weekly_capacity"]:
        raise err.carrier_capacity()

    shipment = new_entity({
        "order_id": order_id,
        "carrier_id": carrier_id,
        "pickup_week": pickup_week,
        "state": "PLANNED",
        "picked_up_at": None,
        "delivered_at": None,
    })
    get_store("shipments")[shipment["id"]] = shipment
    return success_object(shipment, 201)


@bp.get("/wholesale/shipments")
def list_shipments():
    auth_context(SHIPMENT_READ)
    rows = list(get_store("shipments").values())
    for key in ("order_id", "carrier_id", "state", "pickup_week"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


@bp.get("/wholesale/shipments/<sid>")
def get_shipment(sid):
    auth_context(SHIPMENT_READ)
    shipment = get_store("shipments").get(sid)
    if shipment is None:
        raise err.not_found("shipment not found")
    return success_object(shipment)


@bp.post("/wholesale/shipments/<sid>/pickup")
def pickup_shipment(sid):
    auth_context(LOGIS_ONLY)
    shipment = get_store("shipments").get(sid)
    if shipment is None:
        raise err.not_found("shipment not found")
    if shipment["state"] != "PLANNED":
        raise err.invalid_state("shipment is not PLANNED")
    if current_week_monday() < week_monday(shipment["pickup_week"]):
        raise err.window_closed("pickup before pickup_week")
    shipment["state"] = "PICKED_UP"
    shipment["picked_up_at"] = now_iso()
    bump(shipment)
    return success_object(shipment)


@bp.post("/wholesale/shipments/<sid>/deliver")
def deliver_shipment(sid):
    auth_context(LOGIS_ONLY)
    shipment = get_store("shipments").get(sid)
    if shipment is None:
        raise err.not_found("shipment not found")
    if shipment["state"] != "PICKED_UP":
        raise err.invalid_state("shipment is not PICKED_UP")
    shipment["state"] = "DELIVERED"
    shipment["delivered_at"] = now_iso()
    bump(shipment)
    # Cascade: order BUILT -> DELIVERED (PRD §3.8).
    order = get_store("vehicle_orders").get(shipment["order_id"])
    if order is not None and order["state"] == "BUILT":
        order["state"] = "DELIVERED"
        order["delivered_at"] = shipment["delivered_at"]
        bump(order)
        recompute_dml(order["dealer_id"], order["model_line_id"])
    return success_object(shipment)


@bp.post("/wholesale/shipments/<sid>/cancel")
def cancel_shipment(sid):
    auth_context(LOGIS_ONLY)
    shipment = get_store("shipments").get(sid)
    if shipment is None:
        raise err.not_found("shipment not found")
    if shipment["state"] != "PLANNED":
        raise err.invalid_state("shipment is not PLANNED")
    shipment["state"] = "CANCELLED"
    bump(shipment)
    return success_object(shipment)
