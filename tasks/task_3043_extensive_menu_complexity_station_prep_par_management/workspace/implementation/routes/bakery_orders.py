from flask import Blueprint, request

from db import db, new_id
from middleware import get_user_context, require_roles, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, touch, require_fields, check_str, check_enum, check_int,
    resolve, list_paginated, CHEESECAKE_TYPES,
)
from services.calculations import CAKE_UNIT_COST_CENTS, SLICES_PER_CAKE
from errors import ApiError

bp = Blueprint("bakery_orders", __name__)


def serialize(o):
    return {
        "id": o["id"],
        "restaurant_id": o["restaurant_id"],
        "cheesecake_type": o["cheesecake_type"],
        "whole_cakes_ordered": o["whole_cakes_ordered"],
        "whole_cakes_received": o["whole_cakes_received"],
        "provisional_slices": o["provisional_slices"],
        "final_slice_count": o["final_slice_count"],
        "yield_variance": o["yield_variance"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


@bp.route("/api/bakery-orders", methods=["POST"])
def create_order():
    get_user_context()
    body = get_json_body()
    require_fields(body, ["restaurant_id", "cheesecake_type", "whole_cakes_ordered"])
    rid = check_str(body, "restaurant_id")
    ctype = check_enum(body, "cheesecake_type", CHEESECAKE_TYPES)
    cakes = check_int(body, "whole_cakes_ordered", min_value=1)
    require_roles("PastryChef")
    resolve("restaurant", rid)
    ent = {
        "id": new_id(),
        "restaurant_id": rid,
        "cheesecake_type": ctype,
        "whole_cakes_ordered": cakes,
        "whole_cakes_received": None,
        "provisional_slices": None,
        "final_slice_count": None,
        "yield_variance": None,
        "status": "DRAFT",
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.bakery_orders[ent["id"]] = ent
    return success_object(serialize(ent), status=201)


@bp.route("/api/bakery-orders", methods=["GET"])
def list_orders():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.bakery_orders,
        [("restaurant_id", "restaurant_id"), ("status", "status")],
        request.args,
    )
    return success_array([serialize(o) for o in page], limit, offset, total)


@bp.route("/api/bakery-orders/<oid>", methods=["GET"])
def get_order(oid):
    require_roles(*ALL_ROLES)
    o = resolve("bakery_order", oid)
    return success_object(serialize(o))


@bp.route("/api/bakery-orders/<oid>/submit", methods=["POST"])
def submit(oid):
    get_user_context()
    get_json_body()
    require_roles("PastryChef")
    o = resolve("bakery_order", oid)
    if o["status"] != "DRAFT":
        raise ApiError("ERR_BAKERY_ORDER_INVALID_STATE", 409, "submit requires DRAFT order")
    o["status"] = "SUBMITTED"
    touch(o)
    return success_object(serialize(o))


@bp.route("/api/bakery-orders/<oid>/confirm", methods=["POST"])
def confirm(oid):
    get_user_context()
    get_json_body()
    require_roles("InventoryController")
    o = resolve("bakery_order", oid)
    if o["status"] != "SUBMITTED":
        raise ApiError("ERR_BAKERY_ORDER_INVALID_STATE", 409, "confirm requires SUBMITTED order")
    restaurant = resolve("restaurant", o["restaurant_id"])
    amount = o["whole_cakes_ordered"] * CAKE_UNIT_COST_CENTS
    if restaurant["weekly_bakery_budget_spent_cents"] + amount > restaurant["weekly_bakery_budget_cents"]:
        raise ApiError("ERR_BAKERY_BUDGET_EXCEEDED", 402, "Confirm would exceed the weekly bakery budget")
    o["status"] = "CONFIRMED"
    touch(o)
    restaurant["weekly_bakery_budget_spent_cents"] += amount
    touch(restaurant)
    return success_object(serialize(o))


@bp.route("/api/bakery-orders/<oid>/receive", methods=["POST"])
def receive(oid):
    get_user_context()
    body = get_json_body()
    require_fields(body, ["whole_cakes_received"])
    received = check_int(body, "whole_cakes_received")
    require_roles("PastryChef")
    o = resolve("bakery_order", oid)
    if o["status"] != "CONFIRMED":
        raise ApiError("ERR_BAKERY_ORDER_INVALID_STATE", 409, "receive requires CONFIRMED order")
    if received <= 0 or received > o["whole_cakes_ordered"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "whole_cakes_received must be > 0 and <= whole_cakes_ordered")
    o["whole_cakes_received"] = received
    o["provisional_slices"] = received * SLICES_PER_CAKE
    o["status"] = "RECEIVED" if received == o["whole_cakes_ordered"] else "PARTIALLY_RECEIVED"
    touch(o)
    return success_object(serialize(o))


@bp.route("/api/bakery-orders/<oid>/reconcile-yield", methods=["POST"])
def reconcile_yield(oid):
    get_user_context()
    body = get_json_body()
    require_fields(body, ["final_slice_count"])
    final = check_int(body, "final_slice_count", min_value=0)
    require_roles("PastryChef")
    o = resolve("bakery_order", oid)
    if o["status"] not in ("RECEIVED", "PARTIALLY_RECEIVED"):
        raise ApiError("ERR_BAKERY_ORDER_INVALID_STATE", 409, "reconcile-yield requires RECEIVED or PARTIALLY_RECEIVED order")
    o["final_slice_count"] = final
    o["yield_variance"] = final - o["provisional_slices"]
    o["status"] = "RECONCILED"
    touch(o)
    return success_object(serialize(o))


@bp.route("/api/bakery-orders/<oid>/cancel", methods=["POST"])
def cancel(oid):
    get_user_context()
    get_json_body()
    require_roles("PastryChef", "InventoryController")
    o = resolve("bakery_order", oid)
    if o["status"] not in ("DRAFT", "SUBMITTED", "CONFIRMED"):
        raise ApiError("ERR_BAKERY_ORDER_INVALID_STATE", 409, "cancel requires DRAFT, SUBMITTED, or CONFIRMED order")
    was_confirmed = o["status"] == "CONFIRMED"
    o["status"] = "CANCELLED"
    touch(o)
    if was_confirmed:
        restaurant = resolve("restaurant", o["restaurant_id"])
        restaurant["weekly_bakery_budget_spent_cents"] -= o["whole_cakes_ordered"] * CAKE_UNIT_COST_CENTS
        touch(restaurant)
    return success_object(serialize(o))
