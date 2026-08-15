"""Seasonal build plans (PRD §3.11): shelf-life window and zone week-capacity
gates at approval."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_PRODUCT_DISCONTINUED,
    ERR_SHELF_LIFE_WINDOW,
    ERR_ZONE_CAPACITY_EXCEEDED,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from services import MIN_REMAINING_SHELF_DAYS, serialize, _ceil_div
from util import (
    apply_filters,
    body_json,
    check_shape,
    exist_body_fks,
    paginate,
    pagination_params,
    parse_date,
    path_entity,
)

bp = Blueprint("plans", __name__)

PLAN_SPEC = {
    "plan_code": {"type": "string", "required": True},
    "product_id": {"type": "string", "required": True},
    "zone_id": {"type": "string", "required": True},
    "production_week_start": {"type": "date", "required": True},
    "sale_week_start": {"type": "date", "required": True},
    "target_units": {"type": "integer", "min": 1, "required": True},
}


@bp.route("/seasonal-build-plans", methods=["POST"])
def create_plan():
    authenticate({"ProductionPlanner"})
    body = body_json()
    exist_body_fks(body, {
        "product_id": ("products", "product"),
        "zone_id": ("zones", "freezer zone"),
    })
    check_shape(body, PLAN_SPEC)
    product = db.get("products", body["product_id"])
    # Priority 39: DISCONTINUED products cannot be referenced by new build plans.
    if product["status"] != "ACTIVE":
        raise ApiError(ERR_PRODUCT_DISCONTINUED, 422, "product is not ACTIVE")
    plan = db.new_entity("plans", {
        "plan_code": body["plan_code"],
        "product_id": product["id"],
        "zone_id": body["zone_id"],
        "production_week_start": body["production_week_start"],
        "sale_week_start": body["sale_week_start"],
        "target_units": body["target_units"],
        "required_pallets": _ceil_div(body["target_units"], int(product["units_per_pallet"])),
        "status": "DRAFT",
    })
    return success_obj(serialize("plans", plan), 201)


@bp.route("/seasonal-build-plans", methods=["GET"])
def list_plans():
    authenticate(ALL_ROLES)
    items = apply_filters(db.all_of("plans"), ["product_id", "zone_id", "status"])
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("plans", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/seasonal-build-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    authenticate(ALL_ROLES)
    plan = path_entity("plans", plan_id, "build plan")
    return success_obj(serialize("plans", plan))


@bp.route("/seasonal-build-plans/<plan_id>/approve", methods=["POST"])
def approve_plan(plan_id):
    authenticate({"PlantManager"})
    plan = path_entity("plans", plan_id, "build plan")
    if plan["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "plan is not DRAFT")
    product = db.get("products", plan["product_id"])
    zone = db.get("zones", plan["zone_id"])
    # Priority 19: zone week-capacity bucket (same zone, same production week).
    used = sum(
        int(other["required_pallets"])
        for other in db.all_of("plans")
        if other["zone_id"] == plan["zone_id"]
        and other["production_week_start"] == plan["production_week_start"]
        and other["status"] == "APPROVED"
        and other["id"] != plan["id"]
    )
    if used + int(plan["required_pallets"]) > int(zone["pallet_capacity"]):
        raise ApiError(
            ERR_ZONE_CAPACITY_EXCEEDED,
            422,
            "zone week-bucket pallet capacity would be exceeded",
        )
    # Priority 20: shelf-life window (inclusive boundary: equality passes).
    days_between = (
        parse_date(plan["sale_week_start"]) - parse_date(plan["production_week_start"])
    ).days
    if days_between + MIN_REMAINING_SHELF_DAYS > int(product["shelf_life_days"]):
        raise ApiError(
            ERR_SHELF_LIFE_WINDOW,
            422,
            "sale week falls outside the product's shelf-life window",
        )
    plan["status"] = "APPROVED"
    db.touch(plan)
    return success_obj(serialize("plans", plan))


@bp.route("/seasonal-build-plans/<plan_id>/cancel", methods=["POST"])
def cancel_plan(plan_id):
    authenticate({"PlantManager"})
    plan = path_entity("plans", plan_id, "build plan")
    if plan["status"] not in ("DRAFT", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE, 409, "plan cannot be canceled")
    plan["status"] = "CANCELED"
    db.touch(plan)
    return success_obj(serialize("plans", plan))
