"""Activity sessions and activity bookings."""

from flask import Blueprint, jsonify

import db as _db
import errors
import middleware
import response
import validations as v
from services import common, engine

bp = Blueprint("activities", __name__)

DECLARED_SESSION = ("name", "tier_code", "base_price_cents", "capacity_units")
DECLARED_BOOKING = ("activity_session_id", "group_booking_id", "attendees", "reservation_id")

TIER_CODES = ("STANDARD", "PREMIUM", "VIP")


def seats_taken(session_id):
    total = 0
    for booking in _db.store().activity_bookings.values():
        if booking.get("activity_session_id") != session_id:
            continue
        if booking.get("activity_booking_status") in ("PENDING_PAYMENT", "CONFIRMED"):
            total += booking.get("attendees") or 0
    return total


@bp.route("/resorts/<resort_id>/activities", methods=["POST"])
def create_session(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_SESSION)
    middleware.require(caller, "platform_ops")
    common.get_resort(resort_id)

    if not any(
        a.get("resort_id") == resort_id and common.attraction_is_open(a)
        for a in _db.store().attractions.values()
    ):
        raise errors.attraction_not_open()

    name = v.required_str(payload, "name")
    tier_code = v.in_enum(v.required_str(payload, "tier_code"), "tier_code", TIER_CODES)
    base_price = v.required_int(payload, "base_price_cents")
    capacity_units = v.required_int(payload, "capacity_units")
    v.in_range(capacity_units, "capacity_units", low=1)

    session = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "resort_id": resort_id,
        "name": name,
        "tier_code": tier_code,
        "base_price_cents": base_price,
        "capacity_units": capacity_units,
        "opt_in_ratio": None,
        "opt_in_ratio_strict": None,
        "opt_in_ratio_inclusive": None,
        "opt_in_gate": "ADMIT",
    }
    engine.refresh_opt_in(session, resort_id)
    _db.store().activity_sessions[session["id"]] = session
    return jsonify(response.success(common.serialise("activity_session", session))), 201


@bp.route("/resorts/<resort_id>/activities", methods=["GET"])
def list_sessions(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group", "Anonymous")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    rows = [
        s for s in _db.store().activity_sessions.values() if s.get("resort_id") == resort_id
    ]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("activity_session", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/activities/<activity_session_id>", methods=["GET"])
def get_session(resort_id, activity_session_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group", "Anonymous")
    common.get_resort(resort_id)
    session = common.fetch("activity_session", activity_session_id, resort_id)
    return jsonify(response.success(common.serialise("activity_session", session))), 200


@bp.route("/resorts/<resort_id>/activity-bookings", methods=["POST"])
def create_activity_booking(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_BOOKING)
    middleware.require(caller, "Group", "FrontDesk")
    common.get_resort(resort_id)

    session = common.fetch(
        "activity_session", v.required_str(payload, "activity_session_id"), resort_id
    )
    group_booking_id = v.required_str(payload, "group_booking_id")
    middleware.require_group_ownership(caller, group_booking_id)
    common.fetch("group_booking", group_booking_id, resort_id)
    attendees = v.required_int(payload, "attendees")
    v.in_range(attendees, "attendees", low=1)
    reservation = common.fetch(
        "reservation", v.required_str(payload, "reservation_id"), resort_id
    )

    if attendees > session["capacity_units"] - seats_taken(session["id"]):
        raise errors.no_eligible_session()

    booking = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "updated_at": _db.now_iso(),
        "version": 1,
        "resort_id": resort_id,
        "activity_session_id": session["id"],
        "group_booking_id": group_booking_id,
        "attendees": attendees,
        "reservation_id": reservation["id"],
        "activity_booking_status": "PENDING_PAYMENT",
        "activity_rate_total_cents": engine.activity_rate(session, attendees),
        "activity_rate_refund_cents": 0,
    }
    _db.store().activity_bookings[booking["id"]] = booking
    engine.refresh_opt_in(session, resort_id)
    return jsonify(response.success(common.serialise("activity_booking", booking))), 201


@bp.route("/resorts/<resort_id>/activity-bookings", methods=["GET"])
def list_activity_bookings(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    rows = [
        b for b in _db.store().activity_bookings.values() if b.get("resort_id") == resort_id
    ]
    for field in ("group_booking_id", "activity_session_id", "reservation_id"):
        wanted = v.query_str(field)
        if wanted:
            rows = [b for b in rows if b.get(field) == wanted]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("activity_booking", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/activity-bookings/<activity_booking_id>", methods=["GET"])
def get_activity_booking(resort_id, activity_booking_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    common.get_resort(resort_id)
    booking = common.fetch("activity_booking", activity_booking_id, resort_id)
    return jsonify(response.success(common.serialise("activity_booking", booking))), 200


@bp.route("/resorts/<resort_id>/activity-bookings/<activity_booking_id>/confirm", methods=["POST"])
def confirm_activity_booking(resort_id, activity_booking_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "Group", "FrontDesk")
    common.get_resort(resort_id)
    booking = common.fetch("activity_booking", activity_booking_id, resort_id)
    middleware.require_group_ownership(caller, booking["group_booking_id"])

    if booking["activity_booking_status"] != "PENDING_PAYMENT":
        raise errors.invalid_state()

    group = common.get("group_booking", booking["group_booking_id"])
    if group is None or group.get("group_status") != "CONFIRMED":
        raise errors.invalid_state("The linked group booking is not CONFIRMED.")

    booking["activity_booking_status"] = "CONFIRMED"
    common.touch(booking)
    return jsonify(response.success(common.serialise("activity_booking", booking))), 200


@bp.route("/resorts/<resort_id>/activity-bookings/<activity_booking_id>/cancel", methods=["POST"])
def cancel_activity_booking(resort_id, activity_booking_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "Group", "platform_ops")
    common.get_resort(resort_id)
    booking = common.fetch("activity_booking", activity_booking_id, resort_id)
    middleware.require_group_ownership(caller, booking["group_booking_id"])

    if booking["activity_booking_status"] != "CONFIRMED":
        raise errors.invalid_state()

    session = common.get("activity_session", booking["activity_session_id"])
    booking["activity_booking_status"] = "CANCELLED"
    booking["activity_rate_refund_cents"] = engine.activity_refund(
        session, booking["attendees"]
    )
    common.touch(booking)
    return jsonify(response.success(common.serialise("activity_booking", booking))), 200