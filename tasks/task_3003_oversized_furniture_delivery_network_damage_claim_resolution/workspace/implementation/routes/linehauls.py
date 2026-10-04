"""Linehauls: plan, depart, arrive, mark-missed (with the miss cascade)."""
from flask import Blueprint, request

import clock
from db import db, new_id
from errors import (
    err_hub_daily_capacity_exceeded,
    err_invalid_request,
    err_invalid_state,
)
from middleware import require_roles
from response import success
from services import calculations as calc
from services.common import get_or_404, list_response, stamp_new, touch
from validation import get_body, req_date, req_int, req_string

bp = Blueprint("linehauls", __name__)


@bp.post("/linehauls")
@require_roles("NetworkAdmin")
def create_linehaul():
    body = get_body(request)
    raw_hub_id = body.get("hub_id")
    hub = get_or_404(db.hubs, raw_hub_id if isinstance(raw_hub_id, str) else None)
    planned_arrival_date = req_date(body, "planned_arrival_date")
    origin_ship_date = req_date(body, "origin_ship_date")
    capacity = req_int(body, "capacity")
    if capacity < 0:
        raise err_invalid_request("capacity must be >= 0")
    if not origin_ship_date < planned_arrival_date:
        raise err_invalid_request("origin_ship_date must be strictly before planned_arrival_date")
    linehaul = stamp_new(
        {
            "id": new_id(),
            "hub_id": hub["id"],
            "planned_arrival_date": planned_arrival_date.isoformat(),
            "origin_ship_date": origin_ship_date.isoformat(),
            "capacity": capacity,
            "committed_count": 0,
            "status": "PLANNED",
        }
    )
    db.linehauls[linehaul["id"]] = linehaul
    # Side effect: unbound OWNED_FINAL_MILE shipments for this hub auto rebind.
    from routes.orders import try_auto_bind_unbound_shipments

    try_auto_bind_unbound_shipments(hub["id"])
    return success(linehaul, status=201)


@bp.get("/linehauls")
@require_roles("NetworkAdmin", "HubOperator")
def list_linehauls():
    return list_response(
        db.linehauls,
        [
            ("hub_id", "hub_id", None),
            ("status", "status", {"PLANNED", "DEPARTED", "ARRIVED", "MISSED"}),
        ],
    )


@bp.get("/linehauls/<linehaulId>")
@require_roles("NetworkAdmin", "HubOperator")
def get_linehaul(linehaulId):
    return success(get_or_404(db.linehauls, linehaulId))


@bp.post("/linehauls/<linehaulId>/depart")
@require_roles("NetworkAdmin")
def depart_linehaul(linehaulId):
    linehaul = get_or_404(db.linehauls, linehaulId)
    if linehaul["status"] != "PLANNED":
        raise err_invalid_state("Linehaul must be PLANNED to depart")
    linehaul["status"] = "DEPARTED"
    touch(linehaul)
    return success(linehaul)


@bp.post("/linehauls/<linehaulId>/arrive")
@require_roles("HubOperator")
def arrive_linehaul(linehaulId):
    linehaul = get_or_404(db.linehauls, linehaulId)
    if linehaul["status"] != "DEPARTED":
        raise err_invalid_state("Linehaul must be DEPARTED to arrive")
    hub = get_or_404(db.hubs, linehaul["hub_id"])
    arrived_count = sum(
        1
        for lh in db.linehauls.values()
        if lh["hub_id"] == hub["id"]
        and lh["status"] == "ARRIVED"
        and lh["planned_arrival_date"] == linehaul["planned_arrival_date"]
    )
    if arrived_count >= int(hub["daily_capacity"]):
        raise err_hub_daily_capacity_exceeded()
    linehaul["status"] = "ARRIVED"
    touch(linehaul)
    for shipment in db.shipments.values():
        if shipment["linehaul_id"] == linehaul["id"] and shipment["current_state"] == "IN_TRANSIT":
            shipment["current_state"] = "AT_HUB"
            touch(shipment)
    return success(linehaul)


@bp.post("/linehauls/<linehaulId>/mark-missed")
@require_roles("HubOperator")
def mark_missed_linehaul(linehaulId):
    linehaul = get_or_404(db.linehauls, linehaulId)
    if linehaul["status"] != "DEPARTED":
        raise err_invalid_state("Linehaul must be DEPARTED to mark missed")

    affected = [
        s
        for s in db.shipments.values()
        if s["linehaul_id"] == linehaul["id"]
        and s["current_state"] not in ("DELIVERED", "EXCEPTION")
    ]
    affected.sort(key=lambda s: (s["created_at"], s["id"]))

    linehaul["status"] = "MISSED"
    linehaul["committed_count"] -= len(affected)
    touch(linehaul)

    for shipment in affected:
        shipment["linehaul_misses"] += 1
        order = db.orders.get(shipment["order_id"])
        lane = calc.find_active_lane(
            db.freight_lanes.values(),
            shipment["leg_mode"],
            db.customers[order["customer_id"]]["destination_zone"]
            if order and order["customer_id"] in db.customers
            else "",
        )
        if order is not None and lane is not None:
            shipment["promised_date"] = calc.promised_date(
                clock._parse_iso(order["created_at"]).date(),
                lane["transit_days"],
                shipment["fulfillment_mode"],
                shipment["linehaul_misses"],
            )
        shipment["linehaul_id"] = None
        touch(shipment)

    # Rebind each affected shipment to the earliest suitable PLANNED linehaul
    # into the same hub; if none exists it stays unbound until one is planned.
    for shipment in affected:
        new_linehaul = calc.select_linehaul(db.linehauls.values(), linehaul["hub_id"], db.shipments.values())
        if new_linehaul is None:
            break
        shipment["linehaul_id"] = new_linehaul["id"]
        new_linehaul["committed_count"] += 1
        touch(new_linehaul)
        touch(shipment)

    return success(linehaul)
