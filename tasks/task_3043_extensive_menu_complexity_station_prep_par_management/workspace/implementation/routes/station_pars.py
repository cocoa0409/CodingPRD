from flask import Blueprint, request

from db import db, new_id
from middleware import get_user_context, require_roles, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, touch, require_fields, check_int,
    resolve, list_paginated, recompute_par_health,
)
from errors import ApiError

bp = Blueprint("station_pars", __name__)


def serialize(p):
    return {
        "id": p["id"],
        "station_id": p["station_id"],
        "prep_item_id": p["prep_item_id"],
        "par_quantity": p["par_quantity"],
        "proposed_par_quantity": p["proposed_par_quantity"],
        "requested_by_cook_id": p["requested_by_cook_id"],
        "approved_by_cook_id": p["approved_by_cook_id"],
        "adjustment_status": p["adjustment_status"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/api/station-pars", methods=["POST"])
def create_par():
    get_user_context()
    body = get_json_body()
    require_fields(body, ["station_id", "prep_item_id", "par_quantity"])
    sid = body["station_id"]
    pid = body["prep_item_id"]
    pq = check_int(body, "par_quantity", min_value=0)
    require_roles("KitchenManager")
    station = resolve("station", sid)
    item = resolve("prep_item", pid)
    if station["station_type"] != item["station_type"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Station and prep item must share station_type")
    ent = {
        "id": new_id(),
        "station_id": sid,
        "prep_item_id": pid,
        "par_quantity": pq,
        "proposed_par_quantity": None,
        "requested_by_cook_id": None,
        "approved_by_cook_id": None,
        "adjustment_status": "NONE",
        "status": "ACTIVE",
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.station_pars[ent["id"]] = ent
    recompute_par_health(sid)
    return success_object(serialize(ent), status=201)


@bp.route("/api/station-pars", methods=["GET"])
def list_pars():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.station_pars,
        [
            ("station_id", "station_id"),
            ("prep_item_id", "prep_item_id"),
            ("requested_by_cook_id", "requested_by_cook_id"),
            ("status", "status"),
        ],
        request.args,
    )
    return success_array([serialize(p) for p in page], limit, offset, total)


@bp.route("/api/station-pars/<pid>", methods=["GET"])
def get_par(pid):
    require_roles(*ALL_ROLES)
    p = resolve("station_par", pid)
    return success_object(serialize(p))


@bp.route("/api/station-pars/<pid>/propose-adjustment", methods=["POST"])
def propose_adjustment(pid):
    uid, role = get_user_context()
    body = get_json_body()
    require_fields(body, ["proposed_par_quantity", "expected_station_par_version"])
    proposed = check_int(body, "proposed_par_quantity", min_value=0)
    expected = check_int(body, "expected_station_par_version")
    require_roles("LineCook", "PrepCook", "KitchenManager")
    p = resolve("station_par", pid)
    if p["adjustment_status"] == "PENDING":
        raise ApiError("ERR_PAR_ADJUSTMENT_NOT_PENDING", 409, "An adjustment is already pending")
    if expected != p["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_station_par_version does not match current version")
    p["proposed_par_quantity"] = proposed
    p["requested_by_cook_id"] = uid
    p["adjustment_status"] = "PENDING"
    touch(p)
    return success_object(serialize(p))


@bp.route("/api/station-pars/<pid>/approve-adjustment", methods=["POST"])
def approve_adjustment(pid):
    uid, role = get_user_context()
    get_json_body()
    require_roles("KitchenManager")
    p = resolve("station_par", pid)
    if p["adjustment_status"] != "PENDING":
        raise ApiError("ERR_PAR_ADJUSTMENT_NOT_PENDING", 409, "approve requires PENDING adjustment")
    if uid == p["requested_by_cook_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Approver must differ from requester")
    p["par_quantity"] = p["proposed_par_quantity"]
    p["proposed_par_quantity"] = None
    p["approved_by_cook_id"] = uid
    p["adjustment_status"] = "APPROVED"
    touch(p)
    recompute_par_health(p["station_id"])
    return success_object(serialize(p))


@bp.route("/api/station-pars/<pid>/reject-adjustment", methods=["POST"])
def reject_adjustment(pid):
    uid, role = get_user_context()
    get_json_body()
    require_roles("KitchenManager")
    p = resolve("station_par", pid)
    if p["adjustment_status"] != "PENDING":
        raise ApiError("ERR_PAR_ADJUSTMENT_NOT_PENDING", 409, "reject requires PENDING adjustment")
    p["proposed_par_quantity"] = None
    p["adjustment_status"] = "REJECTED"
    touch(p)
    return success_object(serialize(p))
