"""Yield standard routes (PRD §3.7)."""

from flask import Blueprint, request

import db
from errors import invalid_request, unprocessable
from errors import ERR_DUPLICATE_CUT_CODE
from middleware import require_roles
from response import success_list, success_object
from services import domain
from util import base_entity, get_json_body, paginate, req_int, req_number, req_string, touch

bp = Blueprint("yield_standards", __name__)

YS_READ_ROLES = ("PlatformAdmin", "CorporateController", "OperationsAuditor")


@bp.route("/yield-standards", methods=["POST"])
def create_yield_standard():
    require_roles("CorporateController")
    body = get_json_body()
    cut_code = req_string(body, "cut_code")
    expected_yield_pct = req_number(body, "expected_yield_pct")
    waste_tolerance_pct = req_number(body, "waste_tolerance_pct")
    cost = req_int(body, "standard_cost_per_lb_cents")
    if not (0 < expected_yield_pct < 100):
        raise invalid_request("expected_yield_pct must be > 0 and < 100")
    if waste_tolerance_pct < 0:
        raise invalid_request("waste_tolerance_pct must be >= 0")
    if cost <= 0:
        raise invalid_request("standard_cost_per_lb_cents must be > 0")
    # cut_code unique among active standards.
    for y in db.yield_standards.values():
        if y["active"] and y["cut_code"] == cut_code:
            raise unprocessable(ERR_DUPLICATE_CUT_CODE, "An active yield standard with this cut_code exists")
    y = base_entity()
    y.update({
        "cut_code": cut_code,
        "expected_yield_pct": expected_yield_pct,
        "waste_tolerance_pct": waste_tolerance_pct,
        "standard_cost_per_lb_cents": cost,
        "active": True,
    })
    db.yield_standards[y["id"]] = y
    return success_object(domain.ser_yield_standard(y), 201)


@bp.route("/yield-standards", methods=["GET"])
def list_yield_standards():
    require_roles(*YS_READ_ROLES)
    items = list(db.yield_standards.values())
    cut_code = request.args.get("cut_code")
    if cut_code is not None:
        items = [y for y in items if y["cut_code"] == cut_code]
    active = request.args.get("active")
    if active is not None:
        flag = active.lower() in ("true", "1", "yes")
        items = [y for y in items if y["active"] == flag]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_yield_standard(y) for y in page], limit, offset, total)


@bp.route("/yield-standards/<yid>", methods=["GET"])
def get_yield_standard(yid):
    require_roles(*YS_READ_ROLES)
    return success_object(domain.ser_yield_standard(domain.get_yield_standard(yid)))


@bp.route("/yield-standards/<yid>/deactivate", methods=["POST"])
def deactivate_yield_standard(yid):
    require_roles("CorporateController")
    y = domain.get_yield_standard(yid)
    if not y["active"]:
        from errors import conflict, ERR_INVALID_STATE
        raise conflict(ERR_INVALID_STATE, "Yield standard is already deactivated")
    y["active"] = False
    touch(y)
    return success_object(domain.ser_yield_standard(y))
