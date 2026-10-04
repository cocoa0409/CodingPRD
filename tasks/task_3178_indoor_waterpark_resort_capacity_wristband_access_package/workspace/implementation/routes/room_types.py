"""Room type endpoints."""

from flask import Blueprint, jsonify

import db as _db
import middleware
import response
import validations as v
from services import common

bp = Blueprint("room_types", __name__)

DECLARED_CREATE = ("code", "max_occupancy", "base_rate_cents", "is_cabana")


@bp.route("/resorts/<resort_id>/room-types", methods=["POST"])
def create_room_type(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_CREATE)
    middleware.require(caller, "platform_ops")
    common.get_resort(resort_id)

    code = v.required_str(payload, "code")
    max_occupancy = v.required_int(payload, "max_occupancy")
    v.in_range(max_occupancy, "max_occupancy", low=1)
    base_rate = v.required_int(payload, "base_rate_cents")
    is_cabana = v.optional_bool(payload, "is_cabana", False)

    room_type = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "resort_id": resort_id,
        "code": code,
        "max_occupancy": max_occupancy,
        "base_rate_cents": base_rate,
        "is_cabana": is_cabana,
    }
    _db.store().room_types[room_type["id"]] = room_type
    return jsonify(response.success(common.serialise("room_type", room_type))), 201


@bp.route("/resorts/<resort_id>/room-types", methods=["GET"])
def list_room_types(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group", "Anonymous")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    rows = [
        r for r in _db.store().room_types.values() if r.get("resort_id") == resort_id
    ]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("room_type", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/room-types/<room_type_id>", methods=["GET"])
def get_room_type(resort_id, room_type_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group", "Anonymous")
    common.get_resort(resort_id)
    room_type = common.fetch("room_type", room_type_id, resort_id)
    return jsonify(response.success(common.serialise("room_type", room_type))), 200