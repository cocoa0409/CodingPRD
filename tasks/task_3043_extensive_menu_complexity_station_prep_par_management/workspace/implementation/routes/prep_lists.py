from flask import Blueprint, request

from db import db, new_id
from middleware import get_user_context, require_roles, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, touch, require_fields, check_str, check_enum, check_int,
    resolve, list_paginated, cancel_planned_batch, GENERATION_VARIANTS,
)
from services.calculations import forecast_prep_quantity
from errors import ApiError

bp = Blueprint("prep_lists", __name__)


def serialize(p):
    return {
        "id": p["id"],
        "restaurant_id": p["restaurant_id"],
        "demand_forecast_id": p["demand_forecast_id"],
        "generation_variant": p["generation_variant"],
        "lines": p["lines"],
        "total_rounded_quantity": p["total_rounded_quantity"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/api/prep-lists", methods=["POST"])
def create_prep_list():
    get_user_context()
    body = get_json_body()
    require_fields(body, ["restaurant_id", "demand_forecast_id"])
    rid = check_str(body, "restaurant_id")
    fid = check_str(body, "demand_forecast_id")
    require_roles("KitchenManager")
    resolve("restaurant", rid)
    resolve("demand_forecast", fid)
    ent = {
        "id": new_id(),
        "restaurant_id": rid,
        "demand_forecast_id": fid,
        "generation_variant": None,
        "lines": [],
        "total_rounded_quantity": 0,
        "status": "DRAFT",
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.prep_lists[ent["id"]] = ent
    return success_object(serialize(ent), status=201)


@bp.route("/api/prep-lists", methods=["GET"])
def list_prep_lists():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.prep_lists,
        [
            ("restaurant_id", "restaurant_id"),
            ("demand_forecast_id", "demand_forecast_id"),
            ("status", "status"),
        ],
        request.args,
    )
    return success_array([serialize(p) for p in page], limit, offset, total)


@bp.route("/api/prep-lists/<pid>", methods=["GET"])
def get_prep_list(pid):
    require_roles(*ALL_ROLES)
    p = resolve("prep_list", pid)
    return success_object(serialize(p))


@bp.route("/api/prep-lists/<pid>/generate", methods=["POST"])
def generate(pid):
    get_user_context()
    body = get_json_body()
    require_fields(body, ["generation_variant"])
    variant = check_enum(body, "generation_variant", GENERATION_VARIANTS)
    require_roles("KitchenManager")
    pl = resolve("prep_list", pid)
    if pl["status"] != "DRAFT":
        raise ApiError("ERR_PREP_LIST_NOT_DRAFT", 409, "generate requires DRAFT prep list")
    forecast = resolve("demand_forecast", pl["demand_forecast_id"])
    if forecast["status"] != "FINALIZED":
        raise ApiError("ERR_FORECAST_NOT_FINALIZED", 409, "generate requires FINALIZED forecast")
    lines, total = forecast_prep_quantity(pl, forecast, variant)
    pl["lines"] = lines
    pl["total_rounded_quantity"] = total
    pl["generation_variant"] = variant
    pl["status"] = "GENERATED"
    touch(pl)
    return success_object(serialize(pl))


@bp.route("/api/prep-lists/<pid>/regenerate", methods=["POST"])
def regenerate(pid):
    get_user_context()
    body = get_json_body()
    require_fields(body, ["generation_variant", "expected_prep_list_version"])
    variant = check_enum(body, "generation_variant", GENERATION_VARIANTS)
    expected = check_int(body, "expected_prep_list_version")
    require_roles("KitchenManager")
    pl = resolve("prep_list", pid)
    if pl["status"] not in ("GENERATED", "LOCKED"):
        raise ApiError("ERR_PREP_LIST_NOT_REGENERABLE", 409, "regenerate requires GENERATED or LOCKED prep list")
    if expected != pl["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_prep_list_version does not match current version")
    # Cancel all PLANNED child batches, releasing rack load
    for b in list(db.prep_batches.values()):
        if b["prep_list_id"] == pl["id"] and b["status"] == "PLANNED":
            cancel_planned_batch(b)
    forecast = resolve("demand_forecast", pl["demand_forecast_id"])
    lines, total = forecast_prep_quantity(pl, forecast, variant)
    pl["lines"] = lines
    pl["total_rounded_quantity"] = total
    pl["generation_variant"] = variant
    pl["status"] = "GENERATED"
    touch(pl)
    return success_object(serialize(pl))


@bp.route("/api/prep-lists/<pid>/lock", methods=["POST"])
def lock(pid):
    get_user_context()
    get_json_body()
    require_roles("KitchenManager")
    pl = resolve("prep_list", pid)
    if pl["status"] != "GENERATED":
        raise ApiError("ERR_PREP_LIST_NOT_GENERATED", 409, "lock requires GENERATED prep list")
    pl["status"] = "LOCKED"
    touch(pl)
    return success_object(serialize(pl))
