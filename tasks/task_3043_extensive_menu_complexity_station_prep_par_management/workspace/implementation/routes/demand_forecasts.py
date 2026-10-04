from flask import Blueprint, request

from db import db, new_id, clock_now, format_iso
from middleware import get_user_context, require_roles, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, touch, require_fields, check_str, check_int, check_array,
    resolve, list_paginated, parse_datetime_value,
)
from errors import ApiError, err_invalid_request

bp = Blueprint("demand_forecasts", __name__)


def serialize(f):
    return {
        "id": f["id"],
        "restaurant_id": f["restaurant_id"],
        "service_date": f["service_date"],
        "expected_covers": f["expected_covers"],
        "item_mix": f["item_mix"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


@bp.route("/api/demand-forecasts", methods=["POST"])
def create_forecast():
    get_user_context()
    body = get_json_body()
    require_fields(body, ["restaurant_id", "service_date", "expected_covers", "item_mix"])
    rid = check_str(body, "restaurant_id")
    service_dt = parse_datetime_value(body.get("service_date"), "service_date")
    covers = check_int(body, "expected_covers", min_value=1)
    mix = check_array(body, "item_mix")
    entries = []
    for e in mix:
        if not isinstance(e, dict):
            raise err_invalid_request("item_mix entries must be objects")
        rid2 = e.get("recipe_id")
        cnt = e.get("expected_count")
        if not isinstance(rid2, str):
            raise err_invalid_request("item_mix.recipe_id must be a string")
        if isinstance(cnt, bool) or not isinstance(cnt, int) or cnt < 0:
            raise err_invalid_request("item_mix.expected_count must be a non-negative integer")
        entries.append({"recipe_id": rid2, "expected_count": cnt})
    require_roles("KitchenManager")
    resolve("restaurant", rid)
    for e in entries:
        resolve("recipe", e["recipe_id"])
    ent = {
        "id": new_id(),
        "restaurant_id": rid,
        "service_date": format_iso(service_dt),
        "expected_covers": covers,
        "item_mix": entries,
        "status": "DRAFT",
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.demand_forecasts[ent["id"]] = ent
    return success_object(serialize(ent), status=201)


@bp.route("/api/demand-forecasts", methods=["GET"])
def list_forecasts():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.demand_forecasts,
        [("restaurant_id", "restaurant_id"), ("status", "status")],
        request.args,
    )
    return success_array([serialize(f) for f in page], limit, offset, total)


@bp.route("/api/demand-forecasts/<fid>", methods=["GET"])
def get_forecast(fid):
    require_roles(*ALL_ROLES)
    f = resolve("demand_forecast", fid)
    return success_object(serialize(f))


@bp.route("/api/demand-forecasts/<fid>/submit", methods=["POST"])
def submit(fid):
    get_user_context()
    get_json_body()
    require_roles("KitchenManager")
    f = resolve("demand_forecast", fid)
    if f["status"] != "DRAFT":
        raise ApiError("ERR_FORECAST_NOT_DRAFT", 409, "submit requires DRAFT forecast")
    service_dt = parse_datetime_value(f["service_date"], "service_date")
    if not service_dt > clock_now():
        raise ApiError("ERR_FORECAST_DATE_PAST", 422, "service_date must be strictly after the logical clock now")
    f["status"] = "SUBMITTED"
    touch(f)
    return success_object(serialize(f))


@bp.route("/api/demand-forecasts/<fid>/finalize", methods=["POST"])
def finalize(fid):
    get_user_context()
    get_json_body()
    require_roles("KitchenManager")
    f = resolve("demand_forecast", fid)
    if f["status"] != "SUBMITTED":
        raise ApiError("ERR_FORECAST_NOT_SUBMITTED", 409, "finalize requires SUBMITTED forecast")
    f["status"] = "FINALIZED"
    touch(f)
    return success_object(serialize(f))


@bp.route("/api/demand-forecasts/<fid>/amend", methods=["POST"])
def amend(fid):
    get_user_context()
    get_json_body()
    require_roles("KitchenManager")
    f = resolve("demand_forecast", fid)
    if f["status"] != "SUBMITTED":
        raise ApiError("ERR_FORECAST_NOT_SUBMITTED", 409, "amend requires SUBMITTED forecast")
    f["status"] = "DRAFT"
    touch(f)
    return success_object(serialize(f))
