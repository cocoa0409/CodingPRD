"""Supplier offers: register, list, get."""

from flask import Blueprint, request

import db
from common import new_entity, get_or_404, body, require_field, require_enum, require_positive_int
from errors import ApiError
from middleware import require_role, require_any_authenticated
from response import ok, paginate

bp = Blueprint("supplier_offers", __name__)

COMPONENT_KINDS = {"HOTEL", "RENTAL_CAR", "ATTRACTION_TICKET"}


def _get_offer_or_404(offer_id):
    return get_or_404(
        db.supplier_offers, offer_id, "ERR_OFFER_NOT_FOUND", "SupplierOffer"
    )


@bp.route("/supplier-offers", methods=["POST"])
def create_offer():
    require_role("FinanceAnalyst")
    data = body()
    supplier_code = require_field(data, "supplier_code", str)
    kind = require_enum(data, "component_kind", COMPONENT_KINDS)
    dest_id = require_field(data, "destination_station_id", str)
    net = require_positive_int(data, "net_cost_cents", minimum=0)
    sell = require_positive_int(data, "sell_price_cents", minimum=0)
    if dest_id not in db.stations:
        raise ApiError("ERR_STATION_NOT_FOUND", "Station id does not exist", 404)
    ent = new_entity(
        {
            "supplier_code": supplier_code,
            "component_kind": kind,
            "destination_station_id": dest_id,
            "net_cost_cents": net,
            "sell_price_cents": sell,
            "offer_status": "OPEN",
        }
    )
    db.supplier_offers[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/supplier-offers", methods=["GET"])
def list_offers():
    require_any_authenticated()
    items = list(db.supplier_offers.values())
    sc = request.args.get("supplier_code")
    if sc:
        items = [o for o in items if o["supplier_code"] == sc]
    kind = request.args.get("component_kind")
    if kind:
        items = [o for o in items if o["component_kind"] == kind]
    dest = request.args.get("destination_station_id")
    if dest:
        items = [o for o in items if o["destination_station_id"] == dest]
    status = request.args.get("offer_status")
    if status:
        items = [o for o in items if o["offer_status"] == status]
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/supplier-offers/<offer_id>", methods=["GET"])
def get_offer(offer_id):
    require_any_authenticated()
    ent = _get_offer_or_404(offer_id)
    return ok(ent)
