"""Shipment endpoints (PRD 3.5)."""
from flask import Blueprint, request

from auth import get_body, require_roles
from db import bump, store
from envelope import ok, paginate
from errors import api_error
from services import ATTEMPT_CAP
from util import iso3

bp = Blueprint("shipments", __name__)

READ_ROLES = ("LogisticsCoordinator", "ProgramManager", "DealerRep", "PlatformAdmin")

SHIPMENT_EDGES = {
    "PLANNED": {"LOADED"},
    "LOADED": {"IN_TRANSIT"},
    "IN_TRANSIT": {"DELIVERED", "FAILED"},
    "FAILED": {"PLANNED"},
}


def serialize(shipment):
    return dict(shipment)


@bp.route("/cabinet/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    require_roles(*READ_ROLES)
    shipment = store.shipments.get(shipment_id)
    if shipment is None:
        raise api_error("ERR_NOT_FOUND", "shipment not found")
    return ok(serialize(shipment))


@bp.route("/cabinet/shipments", methods=["GET"])
def list_shipments():
    require_roles(*READ_ROLES)
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    items = [s for s in store.shipments.values()
             if (order_id is None or s["order_id"] == order_id)
             and (status is None or s["status"] == status)]
    items = sorted(items, key=lambda s: s["created_at"])
    page, meta = paginate([serialize(s) for s in items])
    return ok(page, 200, meta)


@bp.route("/cabinet/shipments/<shipment_id>/transition", methods=["POST"])
def transition_shipment(shipment_id):
    require_roles("LogisticsCoordinator")
    shipment = store.shipments.get(shipment_id)
    if shipment is None:
        raise api_error("ERR_NOT_FOUND", "shipment not found")
    body = get_body()
    to_status = body.get("to_status")
    if to_status is None:
        raise api_error("ERR_INVALID_REQUEST", "to_status is required")
    current = shipment["status"]
    if to_status not in SHIPMENT_EDGES.get(current, set()):
        raise api_error("ERR_INVALID_STATE",
                        "cannot move shipment from {} to {}".format(current, to_status))
    order = store.orders.get(shipment["order_id"])

    if to_status == "LOADED":
        shipment["status"] = "LOADED"
        bump(shipment)
    elif to_status == "IN_TRANSIT":
        shipment["status"] = "IN_TRANSIT"
        bump(shipment)
        if order is not None and order["status"] == "MFG_COMPLETE":
            order["status"] = "SHIPPED"
            bump(order)
    elif to_status == "DELIVERED":
        shipment["delivered_at"] = iso3(store.clock)
        shipment["status"] = "DELIVERED"
        bump(shipment)
        if order is not None and order["status"] == "SHIPPED":
            order["status"] = "DELIVERED"
            bump(order)
    elif to_status == "FAILED":
        shipment["attempt_count"] += 1
        shipment["status"] = "FAILED"
        bump(shipment)
        if shipment["attempt_count"] >= ATTEMPT_CAP:
            # Third failed attempt: auto FAILED -> RETURNED.
            shipment["status"] = "RETURNED"
            bump(shipment)
    else:  # FAILED -> PLANNED re-plan (attempt_count < 3 guaranteed by state)
        shipment["status"] = "PLANNED"
        bump(shipment)
    return ok(serialize(shipment))
