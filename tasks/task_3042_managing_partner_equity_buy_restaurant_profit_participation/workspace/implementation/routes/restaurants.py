"""Restaurant routes (PRD §3.2)."""

from flask import Blueprint, request

import db
from errors import conflict, unprocessable
from errors import ERR_INVALID_STATE, ERR_RESTAURANT_HAS_OPEN_CONTRACTS
from middleware import require_roles, ALL_ROLES
from response import success_list, success_object
from services import domain
from util import base_entity, get_json_body, paginate, req_string, touch

bp = Blueprint("restaurants", __name__)


@bp.route("/restaurants", methods=["POST"])
def create_restaurant():
    require_roles("PlatformAdmin")
    body = get_json_body()
    name = req_string(body, "name")
    city = req_string(body, "city")
    state_code = req_string(body, "state_code")
    market_group_id = body.get("market_group_id")
    if market_group_id is not None:
        # Body FK existence (tier 4).
        domain.ref_market_group(market_group_id)
    r = base_entity()
    r.update({
        "name": name,
        "city": city,
        "state_code": state_code,
        "market_group_id": market_group_id,
        "status": "PRE_OPENING",
    })
    db.restaurants[r["id"]] = r
    return success_object(domain.ser_restaurant(r), 201)


@bp.route("/restaurants", methods=["GET"])
def list_restaurants():
    require_roles(*ALL_ROLES)
    items = list(db.restaurants.values())
    mg = request.args.get("market_group_id")
    if mg is not None:
        items = [r for r in items if r.get("market_group_id") == mg]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_restaurant(r) for r in page], limit, offset, total)


@bp.route("/restaurants/<rid>", methods=["GET"])
def get_restaurant(rid):
    require_roles(*ALL_ROLES)
    return success_object(domain.ser_restaurant(domain.get_restaurant(rid)))


@bp.route("/restaurants/<rid>/activate", methods=["POST"])
def activate_restaurant(rid):
    require_roles("PlatformAdmin")
    r = domain.get_restaurant(rid)
    if r["status"] != "PRE_OPENING":
        raise conflict(ERR_INVALID_STATE, "Restaurant must be PRE_OPENING to activate")
    r["status"] = "ACTIVE"
    touch(r)
    return success_object(domain.ser_restaurant(r))


@bp.route("/restaurants/<rid>/close", methods=["POST"])
def close_restaurant(rid):
    require_roles("PlatformAdmin")
    r = domain.get_restaurant(rid)
    if r["status"] != "ACTIVE":
        raise conflict(ERR_INVALID_STATE, "Restaurant must be ACTIVE to close")
    open_contracts = any(
        c["restaurant_id"] == r["id"] and c["status"] in domain.CONTRACT_OPEN_STATUSES
        for c in db.contracts.values()
    )
    if open_contracts:
        raise unprocessable(
            ERR_RESTAURANT_HAS_OPEN_CONTRACTS,
            "Restaurant close is blocked by open contracts",
        )
    r["status"] = "CLOSED"
    touch(r)
    return success_object(domain.ser_restaurant(r))
