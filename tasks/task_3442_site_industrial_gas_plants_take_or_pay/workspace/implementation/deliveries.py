"""Deliveries (PRD 3.6): get, list, physical confirmation."""
from flask import Blueprint, request

from helpers import (authenticate, require_role, json_body, respond,
                     v_int, as_int, by_created, paginate)
from store import db, pub, touch, now_iso, ApiError
from domain import headroom_liters

bp = Blueprint("deliveries", __name__)


def _get_delivery_or_404(delivery_id):
    ent = db["deliveries"].get(delivery_id)
    if ent is None:
        raise ApiError("ERR_DELIVERY_NOT_FOUND", 404, "Delivery not found")
    return ent


@bp.route("/gas-supply/deliveries/<deliveryId>", methods=["GET"])
def get_delivery(deliveryId):
    authenticate()
    return respond(pub(_get_delivery_or_404(deliveryId)))


@bp.route("/gas-supply/deliveries", methods=["GET"])
def list_deliveries():
    authenticate()
    items = list(db["deliveries"].values())
    for f in ("tank_id", "customer_id", "transport_status", "quality_status"):
        val = request.args.get(f)
        if val is not None:
            items = [d for d in items if d.get(f) == val]
    items = by_created(items)
    page, meta = paginate(items)
    return respond([pub(d) for d in page], "array", 200, meta)


@bp.route("/gas-supply/deliveries/<deliveryId>/confirm-delivery",
          methods=["POST"])
def confirm_delivery(deliveryId):
    _uid, role = authenticate()
    require_role(role, {"PipelineDispatcher"})
    ent = _get_delivery_or_404(deliveryId)
    body = json_body()
    # Tier 4: only from SCHEDULED
    if ent["transport_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a SCHEDULED delivery can be confirmed")
    # Tier 5: delivered quantity within [1, current headroom]
    qty = as_int(body.get("delivered_quantity_liters"))
    if qty is not None:
        tank = db["tanks"].get(ent["tank_id"])
        headroom = headroom_liters(tank) if tank is not None else 0
        if qty < 1 or qty > headroom:
            raise ApiError("ERR_DELIVERY_OVERFILL", 422,
                           "delivered_quantity_liters outside [1, tank "
                           "headroom]")
    # Tier 9 structural
    qty = v_int(body, "delivered_quantity_liters")
    ent["delivered_quantity_liters"] = qty
    ent["confirmed_at"] = now_iso()
    ent["transport_status"] = "DELIVERED"
    touch(ent)
    return respond(pub(ent))
