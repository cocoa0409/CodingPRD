"""Attraction endpoints, including the housekeeping pass."""

from flask import Blueprint, jsonify

import db as _db
import middleware
import response
import validations as v
from services import common, engine

bp = Blueprint("attractions", __name__)

DECLARED_CREATE = ("name", "min_occupancy_units", "required_certification")

CERTIFICATIONS = ("LIFEGUARD", "NONE")


@bp.route("/resorts/<resort_id>/attractions", methods=["POST"])
def create_attraction(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_CREATE)
    middleware.require(caller, "platform_ops", "AquaticsManager")
    common.get_resort(resort_id)

    name = v.required_str(payload, "name")
    min_units = v.required_int(payload, "min_occupancy_units")
    v.in_range(min_units, "min_occupancy_units", low=0)
    certification = v.in_enum(
        v.required_str(payload, "required_certification"),
        "required_certification",
        CERTIFICATIONS,
    )

    attraction = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "resort_id": resort_id,
        "name": name,
        "min_occupancy_units": min_units,
        "required_certification": certification,
        "attraction_status": "CLOSED",
    }
    _db.store().attractions[attraction["id"]] = attraction
    return jsonify(response.success(common.serialise("attraction", attraction))), 201


@bp.route("/resorts/<resort_id>/attractions", methods=["GET"])
def list_attractions(resort_id):
    caller = middleware.authenticate()
    middleware.require(
        caller, "platform_ops", "AquaticsManager", "FrontDesk",
        "GateAttendant", "Group", "Anonymous",
    )
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    rows = [
        a for a in _db.store().attractions.values() if a.get("resort_id") == resort_id
    ]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("attraction", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/attractions/<attraction_id>", methods=["GET"])
def get_attraction(resort_id, attraction_id):
    caller = middleware.authenticate()
    middleware.require(
        caller, "platform_ops", "AquaticsManager", "FrontDesk",
        "GateAttendant", "Group", "Anonymous",
    )
    common.get_resort(resort_id)
    attraction = common.fetch("attraction", attraction_id, resort_id)
    return jsonify(response.success(common.serialise("attraction", attraction))), 200


@bp.route("/resorts/<resort_id>/attractions/<attraction_id>/water-quality-logs", methods=["GET"])
def list_attraction_logs(resort_id, attraction_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "AquaticsManager")
    common.get_resort(resort_id)
    common.fetch("attraction", attraction_id, resort_id)
    limit, offset = v.query_pagination()
    rows = [
        log for log in _db.store().water_quality_logs.values()
        if log.get("resort_id") == resort_id and log.get("attraction_id") == attraction_id
    ]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("water_quality_log", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/attractions/<attraction_id>/run_ops", methods=["POST"])
def run_ops(resort_id, attraction_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "platform_ops", "AquaticsManager")
    resort = common.get_resort(resort_id)
    attraction = common.fetch("attraction", attraction_id, resort_id)

    current = common.current_service_date(resort_id)
    for booking in _db.store().cabana_bookings.values():
        if booking.get("resort_id") != resort_id:
            continue
        if booking.get("cabana_booking_status") != "BOOKED":
            continue
        if (booking.get("service_date") or "") < current:
            booking["cabana_booking_status"] = "COMPLETED"
            common.touch(booking)
            cabana = common.get("cabana", booking.get("cabana_id"))
            if cabana is not None:
                cabana["cabana_status"] = "AVAILABLE"
                common.touch(cabana)

    common.recompute_attraction_status(resort_id, attraction_id)
    resort["ops_run_index"] = (resort.get("ops_run_index") or 0) + 1
    common.touch(resort, mutate=False)
    return jsonify(response.success(common.serialise("attraction", attraction))), 200