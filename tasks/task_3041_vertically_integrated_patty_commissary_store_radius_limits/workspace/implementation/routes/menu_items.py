"""MenuItem routes."""

from flask import Blueprint, request

import db
import services.domain as domain
from errors import invalid_request
from middleware import require_roles
from response import success_list, success_object
from util import (
    base_entity,
    get_json_body,
    opt_bool,
    paginate,
    req_int,
    req_string,
)

bp = Blueprint("menu_items", __name__)

READ_ROLES = (
    "SupplyChainDirector", "CommissaryPlanner", "Associate", "StoreManager",
    "RealEstatePlanner", "HRDirector", "QualityAuditor",
)
GET_ROLES = ("SupplyChainDirector", "CommissaryPlanner", "Associate", "StoreManager")


@bp.route("/menu-items", methods=["POST"])
def create_menu_item():
    require_roles("SupplyChainDirector")
    body = get_json_body()
    sku = req_string(body, "sku")
    name = req_string(body, "name")
    base_price_cents = req_int(body, "base_price_cents")
    patty_count = req_int(body, "patty_count")
    produce_units = req_int(body, "produce_units")
    active = opt_bool(body, "active", True)
    m = base_entity()
    m.update({
        "sku": sku,
        "name": name,
        "base_price_cents": base_price_cents,
        "patty_count": patty_count,
        "produce_units": produce_units,
        "active": active,
    })
    db.menu_items[m["id"]] = m
    return success_object(domain.ser_menu_item(m), 201)


@bp.route("/menu-items", methods=["GET"])
def list_menu_items():
    require_roles(*READ_ROLES)
    items = list(db.menu_items.values())
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [m for m in items if m["active"] == want]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_menu_item(m) for m in page], limit, offset, total)


@bp.route("/menu-items/<mid>", methods=["GET"])
def get_menu_item(mid):
    require_roles(*GET_ROLES)
    return success_object(domain.ser_menu_item(domain.get_menu_item(mid)))
