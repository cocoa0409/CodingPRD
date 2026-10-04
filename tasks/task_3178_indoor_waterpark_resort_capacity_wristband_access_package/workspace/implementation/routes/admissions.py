"""Gate admission endpoints."""

from flask import Blueprint, jsonify

import db as _db
import errors
import middleware
import response
import validations as v
from services import common, engine

bp = Blueprint("admissions", __name__)

DECLARED_CREATE = ("wristband_id", "service_date", "direction")

DIRECTIONS = ("IN", "OUT")


def record_rejected(resort_id, band, service_date, direction):
    event = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "updated_at": _db.now_iso(),
        "version": 1,
        "resort_id": resort_id,
        "wristband_id": band["id"] if band else None,
        "service_date": service_date,
        "direction": direction,
        "event_status": "REJECTED",
        "units_delta": 0,
    }
    _db.store().admission_events[event["id"]] = event
    if band is not None:
        common.touch(band)
    return event


def group_booking_for_band(band):
    if band.get("holder_type") != "GROUP_MEMBER" or not band.get("group_member_id"):
        return None
    member = common.get("group_member", band.get("group_member_id"))
    if member is None:
        return None
    return common.get("group_booking", member.get("group_booking_id"))


def group_in_already_accepted(resort_id, group_booking_id, excluding_wristband_id):
    member_ids = {m["id"] for m in engine.members_for_group(group_booking_id)}
    for event in _db.store().admission_events.values():
        if event.get("resort_id") != resort_id:
            continue
        if event.get("direction") != "IN" or event.get("event_status") != "ACCEPTED":
            continue
        if event.get("wristband_id") == excluding_wristband_id:
            continue
        band = common.get("wristband", event.get("wristband_id"))
        if band is not None and band.get("group_member_id") in member_ids:
            return True
    return False


def holder_units(band):
    """Occupancy units the presenting band's holder consumes (PRD 3.5)."""
    if band.get("holder_type") == "RESERVATION_GUEST":
        reservation = common.get("reservation", band.get("reservation_id"))
        return reservation.get("waterpark_included_units") if reservation else 0
    if band.get("holder_type") == "GROUP_MEMBER":
        member = common.get("group_member", band.get("group_member_id"))
        return member.get("member_units") if member else 0
    return 1


@bp.route("/resorts/<resort_id>/admissions", methods=["POST"])
def post_admission(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_CREATE)
    middleware.require(caller, "GateAttendant")
    resort = common.get_resort(resort_id)

    band = common.fetch("wristband", v.required_str(payload, "wristband_id"), resort_id)
    service_date = v.required_service_date(payload, "service_date")
    direction = v.in_enum(v.required_str(payload, "direction"), "direction", DIRECTIONS)

    if resort["pool_posture"] != "OPEN":
        raise errors.pool_closed()

    if not any(
        a.get("resort_id") == resort_id and common.attraction_is_open(a)
        for a in _db.store().attractions.values()
    ):
        raise errors.attraction_not_open()

    day_pass = None
    if band.get("holder_type") == "DAY_PASS_GUEST" and band.get("day_pass_id"):
        day_pass = common.get("day_pass", band.get("day_pass_id"))

    if direction == "IN" and day_pass is not None:
        reserved_remaining = day_pass.get("units_requested") \
            if day_pass.get("day_pass_status") == "RESERVED" else 0
        if reserved_remaining < holder_units(band):
            raise errors.day_pass_units_exhausted()

    if direction == "IN":
        if common.day_pass_reserved_units(resort_id, service_date) > resort["day_pass_cap_units"]:
            raise errors.day_pass_cap_exceeded()
        total = (
            common.room_units_reserved(resort_id, service_date)
            + common.group_units(resort_id, service_date)
            + common.day_pass_reserved_units(resort_id, service_date)
        )
        if total > resort["park_capacity_occupancy_units"]:
            raise errors.park_capacity_exceeded()

    if band.get("access_status") != "GRANTED":
        return jsonify(response.success(common.serialise(
            "admission_event", record_rejected(resort_id, band, service_date, direction)
        ))), 201

    group_booking = group_booking_for_band(band)
    if direction == "IN" and group_booking is not None:
        if group_in_already_accepted(resort_id, group_booking["id"], band["id"]):
            raise errors.group_split_admission()

    units = holder_units(band)
    delta = units if direction == "IN" else -units

    event = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "updated_at": _db.now_iso(),
        "version": 1,
        "resort_id": resort_id,
        "wristband_id": band["id"],
        "service_date": service_date,
        "direction": direction,
        "event_status": "ACCEPTED",
        "units_delta": delta,
    }
    _db.store().admission_events[event["id"]] = event
    common.touch(band)

    if direction == "IN":
        if day_pass is not None and day_pass.get("day_pass_status") == "RESERVED":
            day_pass["day_pass_status"] = "ADMITTED"
            common.touch(day_pass)
        if group_booking is not None:
            engine.recompute_group_reserved(group_booking)
        common.recompute_pool_posture(resort_id)

    return jsonify(response.success(
        common.serialise("admission_event", event)
    )), 201


@bp.route("/resorts/<resort_id>/admissions", methods=["GET"])
def list_admissions(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "GateAttendant", "AquaticsManager")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    rows = [
        e for e in _db.store().admission_events.values() if e.get("resort_id") == resort_id
    ]
    wristband_id = v.query_str("wristband_id")
    if wristband_id:
        rows = [e for e in rows if e.get("wristband_id") == wristband_id]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("admission_event", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/admissions/<admission_event_id>", methods=["GET"])
def get_admission(resort_id, admission_event_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "GateAttendant", "AquaticsManager")
    common.get_resort(resort_id)
    event = common.fetch("admission_event", admission_event_id, resort_id)
    return jsonify(response.success(common.serialise("admission_event", event))), 200