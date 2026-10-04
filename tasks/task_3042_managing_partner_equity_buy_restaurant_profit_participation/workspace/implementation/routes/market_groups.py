"""Market group routes (PRD §3.2)."""

from flask import Blueprint, request

import db
from errors import conflict, unprocessable
from errors import ERR_INVALID_STATE, ERR_MARKET_GROUP_NOT_ACTIVE
from middleware import require_roles, ALL_ROLES
from response import success_list, success_object
from services import domain
from util import base_entity, get_json_body, paginate, req_string, touch

bp = Blueprint("market_groups", __name__)


@bp.route("/market-groups", methods=["POST"])
def create_market_group():
    require_roles("PlatformAdmin")
    body = get_json_body()
    name = req_string(body, "name")
    g = base_entity()
    g.update({"name": name, "status": "FORMING"})
    db.market_groups[g["id"]] = g
    return success_object(domain.ser_market_group(g), 201)


@bp.route("/market-groups", methods=["GET"])
def list_market_groups():
    require_roles(*ALL_ROLES)
    items = list(db.market_groups.values())
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_market_group(g) for g in page], limit, offset, total)


@bp.route("/market-groups/<gid>", methods=["GET"])
def get_market_group(gid):
    require_roles(*ALL_ROLES)
    return success_object(domain.ser_market_group(domain.get_market_group(gid)))


@bp.route("/market-groups/<gid>/activate", methods=["POST"])
def activate_market_group(gid):
    require_roles("PlatformAdmin")
    g = domain.get_market_group(gid)
    if g["status"] != "FORMING":
        raise conflict(ERR_INVALID_STATE, "Market group must be FORMING to activate")
    # Group activation requires at least one ACTIVE restaurant assigned to the group.
    has_active = any(
        r.get("market_group_id") == g["id"] and r["status"] == "ACTIVE"
        for r in db.restaurants.values()
    )
    if not has_active:
        raise unprocessable(
            ERR_MARKET_GROUP_NOT_ACTIVE,
            "Market group activation requires at least one ACTIVE restaurant",
        )
    g["status"] = "ACTIVE"
    touch(g)
    return success_object(domain.ser_market_group(g))
