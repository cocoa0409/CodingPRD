from flask import Blueprint, request

from db import db, new_id
from middleware import get_user_context, require_roles, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, touch, require_fields, check_str, check_int,
    resolve, list_paginated,
)
from errors import err_invalid_request

bp = Blueprint("restaurants", __name__)


def serialize(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "code": r["code"],
        "weekly_bakery_budget_cents": r["weekly_bakery_budget_cents"],
        "weekly_bakery_budget_spent_cents": r["weekly_bakery_budget_spent_cents"],
        "current_waitlist_minutes": r["current_waitlist_minutes"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/api/restaurants", methods=["POST"])
def create_restaurant():
    get_user_context()
    body = get_json_body()
    require_fields(body, ["name", "code", "weekly_bakery_budget_cents"])
    name = check_str(body, "name")
    code = check_str(body, "code")
    budget = check_int(body, "weekly_bakery_budget_cents", min_value=0)
    require_roles("SystemAdmin")
    ent = {
        "id": new_id(),
        "name": name,
        "code": code,
        "weekly_bakery_budget_cents": budget,
        "weekly_bakery_budget_spent_cents": 0,
        "current_waitlist_minutes": 0,
        "status": "ACTIVE",
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.restaurants[ent["id"]] = ent
    return success_object(serialize(ent), status=201)


@bp.route("/api/restaurants", methods=["GET"])
def list_restaurants():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.restaurants, [("status", "status")], request.args
    )
    return success_array([serialize(r) for r in page], limit, offset, total)


@bp.route("/api/restaurants/<rid>", methods=["GET"])
def get_restaurant(rid):
    require_roles(*ALL_ROLES)
    r = resolve("restaurant", rid)
    return success_object(serialize(r))


@bp.route("/api/restaurants/<rid>/update-waitlist", methods=["POST"])
def update_waitlist(rid):
    get_user_context()
    body = get_json_body()
    require_fields(body, ["waitlist_minutes"])
    minutes = check_int(body, "waitlist_minutes", min_value=0)
    require_roles("KitchenManager")
    r = resolve("restaurant", rid)
    r["current_waitlist_minutes"] = minutes
    touch(r)
    return success_object(serialize(r))
