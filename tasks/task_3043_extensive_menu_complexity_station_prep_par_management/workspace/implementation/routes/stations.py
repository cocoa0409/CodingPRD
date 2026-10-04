from flask import Blueprint, request

from db import db, new_id
from middleware import get_user_context, require_roles, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, require_fields, check_str, check_enum, check_int, check_array,
    resolve, list_paginated, STATION_TYPES, rack_load,
)
from services.calculations import compute_station_load_score, compute_overprep_penalty
from errors import ApiError, err_invalid_request

bp = Blueprint("stations", __name__)


def serialize(s):
    return {
        "id": s["id"],
        "restaurant_id": s["restaurant_id"],
        "name": s["name"],
        "station_type": s["station_type"],
        "rack_slot_capacity": s["rack_slot_capacity"],
        "mise_en_place_layout": s["mise_en_place_layout"],
        "par_health": s["par_health"],
        "active": s["active"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/api/stations", methods=["POST"])
def create_station():
    get_user_context()
    body = get_json_body()
    require_fields(body, ["restaurant_id", "name", "station_type", "rack_slot_capacity"])
    rid = check_str(body, "restaurant_id")
    name = check_str(body, "name")
    stype = check_enum(body, "station_type", STATION_TYPES)
    cap = check_int(body, "rack_slot_capacity", min_value=1)
    layout = check_array(body, "mise_en_place_layout", required=False, default=[])
    for pid in layout:
        if not isinstance(pid, str):
            raise err_invalid_request("mise_en_place_layout elements must be strings")
    require_roles("KitchenManager")
    resolve("restaurant", rid)
    for pid in layout:
        resolve("prep_item", pid)
    for pid in layout:
        item = db.prep_items[pid]
        if item["status"] != "ACTIVE":
            raise ApiError("ERR_PREP_ITEM_NOT_ACTIVE", 422, "Layout references a RETIRED prep item")
    ent = {
        "id": new_id(),
        "restaurant_id": rid,
        "name": name,
        "station_type": stype,
        "rack_slot_capacity": cap,
        "mise_en_place_layout": layout,
        "par_health": "OK",
        "active": True,
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.stations[ent["id"]] = ent
    return success_object(serialize(ent), status=201)


@bp.route("/api/stations", methods=["GET"])
def list_stations():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.stations,
        [("restaurant_id", "restaurant_id"), ("station_type", "station_type")],
        request.args,
    )
    return success_array([serialize(s) for s in page], limit, offset, total)


@bp.route("/api/stations/<sid>", methods=["GET"])
def get_station(sid):
    require_roles(*ALL_ROLES)
    s = resolve("station", sid)
    return success_object(serialize(s))


@bp.route("/api/stations/<sid>/throughput-summary", methods=["GET"])
def throughput_summary(sid):
    require_roles(*ALL_ROLES)
    s = resolve("station", sid)
    restaurant = db.restaurants.get(s["restaurant_id"])
    load_score = compute_station_load_score(s, restaurant)
    waste_ratio, penalty = compute_overprep_penalty(sid)
    data = {
        "station_id": sid,
        "load_score": load_score,
        "waste_ratio": waste_ratio,
        "overprep_penalty_points": penalty,
        "par_health": s["par_health"],
        "rack_load": rack_load(sid),
    }
    return success_object(data)
