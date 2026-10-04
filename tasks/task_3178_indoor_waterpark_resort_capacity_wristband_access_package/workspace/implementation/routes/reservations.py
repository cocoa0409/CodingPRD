"""Reservation endpoints: booking, revision, check-in, check-out, cancellation."""

from flask import Blueprint, jsonify

import db as _db
import errors
import middleware
import response
import validations as v
from services import common, engine

bp = Blueprint("reservations", __name__)

DECLARED_CREATE = ("room_type_id", "guest_count", "arrival_date", "departure_date")
DECLARED_UPDATE = ("room_type_id", "guest_count", "arrival_date", "departure_date")
DECLARED_ARCADE = ("wristband_id", "amount_cents")


def recompute_package(reservation, room_type):
    nights = engine.nights_between(
        reservation["arrival_date"], reservation["departure_date"]
    )
    reservation["nights"] = nights
    _, _, total, withheld = engine.package_terms(
        room_type, nights, reservation["waterpark_included_units"]
    )
    reservation["package_rate_total_cents"] = total
    reservation["package_rate_withheld_cents"] = withheld


def linkres(resort_id, reservation_id, allow_anonymous=False):
    common.get_resort(resort_id)
    return common.fetch("reservation", reservation_id, resort_id)


@bp.route("/resorts/<resort_id>/reservations", methods=["POST"])
def create_reservation(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_CREATE)
    middleware.require(caller, "Group", "FrontDesk")
    common.get_resort(resort_id)

    room_type = common.fetch("room_type", v.required_str(payload, "room_type_id"), resort_id)
    guest_count = v.required_int(payload, "guest_count")
    v.in_range(guest_count, "guest_count", low=1, high=room_type["max_occupancy"])
    arrival_date = v.required_service_date(payload, "arrival_date")
    departure_date = v.required_service_date(payload, "departure_date")

    nights = engine.nights_between(arrival_date, departure_date)
    if nights < 1:
        raise errors.invalid_request("departure_date must fall after arrival_date.")

    reservation_id = _db.new_id()
    now = _db.now_iso()
    reservation = {
        "id": reservation_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "resort_id": resort_id,
        "room_type_id": room_type["id"],
        "booking_status": "RESERVED",
        "stay_status": "NOT_STARTED",
        "guest_count": guest_count,
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "nights": nights,
        "waterpark_included_units": guest_count,
        "reserved_units": guest_count,
        "package_rate_total_cents": 0,
        "package_rate_withheld_cents": 0,
        "credited_arcade_cents": 0,
        "checked_in_at": None,
        "checked_out_at": None,
    }
    recompute_package(reservation, room_type)
    _db.store().reservations[reservation_id] = reservation
    return jsonify(response.success(common.serialise("reservation", reservation))), 201


@bp.route("/resorts/<resort_id>/reservations", methods=["GET"])
def list_reservations(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    rows = [
        r for r in _db.store().reservations.values() if r.get("resort_id") == resort_id
    ]
    room_type_id = v.query_str("room_type_id")
    if room_type_id:
        rows = [r for r in rows if r.get("room_type_id") == room_type_id]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("reservation", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/reservations/<reservation_id>", methods=["GET"])
def get_reservation(resort_id, reservation_id):
    caller = middleware.authenticate()
    middleware.require(
        caller, "platform_ops", "FrontDesk", "Group", "Anonymous"
    )
    reservation = linkres(resort_id, reservation_id)
    return jsonify(response.success(common.serialise("reservation", reservation))), 200


@bp.route("/resorts/<resort_id>/reservations/<reservation_id>", methods=["PUT"])
def update_reservation(resort_id, reservation_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_UPDATE)
    middleware.require(caller, "FrontDesk")
    reservation = linkres(resort_id, reservation_id)

    if reservation["booking_status"] != "RESERVED":
        raise errors.invalid_state()

    room_type_id = v.optional_str(payload, "room_type_id", reservation["room_type_id"])
    room_type = common.fetch("room_type", room_type_id, resort_id)
    guest_count = v.optional_int(payload, "guest_count", reservation["guest_count"])
    v.in_range(guest_count, "guest_count", low=1, high=room_type["max_occupancy"])
    arrival_date = v.optional_service_date(payload, "arrival_date", reservation["arrival_date"])
    departure_date = v.optional_service_date(payload, "departure_date", reservation["departure_date"])
    nights = engine.nights_between(arrival_date, departure_date)
    if nights < 1:
        raise errors.invalid_request("departure_date must fall after arrival_date.")

    reservation["room_type_id"] = room_type["id"]
    reservation["guest_count"] = guest_count
    reservation["waterpark_included_units"] = guest_count
    reservation["arrival_date"] = arrival_date
    reservation["departure_date"] = departure_date
    if reservation["stay_status"] == "IN_HOUSE":
        reservation["reserved_units"] = guest_count
    else:
        reservation["reserved_units"] = guest_count
    recompute_package(reservation, room_type)
    common.touch(reservation)
    return jsonify(response.success(common.serialise("reservation", reservation))), 200


@bp.route("/resorts/<resort_id>/reservations/<reservation_id>/check_in", methods=["POST"])
def check_in(resort_id, reservation_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "FrontDesk")
    reservation = linkres(resort_id, reservation_id)

    if reservation["booking_status"] != "RESERVED" or reservation["stay_status"] != "NOT_STARTED":
        raise errors.invalid_state()

    resort = common.get_resort(resort_id)
    _db.store().reservations[reservation_id]["stay_status"] = "IN_HOUSE"
    reservation["checked_in_at"] = _db.now_iso()
    reservation["reserved_units"] = reservation["waterpark_included_units"]
    reservation["credited_arcade_cents"] = engine.arcade_credit_accrual(resort, reservation)

    # Every guest band gains room-charge privilege for the party's ceiling.
    for band in engine.reservation_guest_bands(reservation_id):
        band["room_charge_enabled"] = True
        band["arcade_credit_limit_cents"] = engine.arcade_credit_accrual(resort, reservation)
        common.touch(band)
        engine.recompute_arcade(band)

    # Day-pass bands on the arrival date are displaced by the room package.
    arrival_date = reservation["arrival_date"]
    for band in list(_db.store().wristbands.values()):
        if band.get("resort_id") != resort_id:
            continue
        if band.get("holder_type") != "DAY_PASS_GUEST":
            continue
        if band.get("valid_on_service_date") != arrival_date:
            continue
        if band.get("wristband_status") in ("ISSUED", "ACTIVE"):
            engine.revoke_band(band, None, "WRISTBAND_REVOKED")

    engine.refresh_attractions_after_band_change(resort_id)
    common.touch(reservation)
    return jsonify(response.success(common.serialise("reservation", reservation))), 200


@bp.route("/resorts/<resort_id>/reservations/<reservation_id>/check_out", methods=["POST"])
def check_out(resort_id, reservation_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "FrontDesk")
    reservation = linkres(resort_id, reservation_id)

    # PRD 3.2: a repeated check-out is not refused; it still moves the stay to
    # DEPARTED and re-stamps checked_out_at.  Only a booking that never checked
    # in at all has no departure to close out.
    if reservation["stay_status"] == "DEPARTED" and \
            reservation["booking_status"] != "CHECKED_OUT":
        raise errors.invalid_state()

    bands = [
        b for b in engine.reservation_guest_bands(reservation_id)
        if b.get("wristband_status") in ("ISSUED", "ACTIVE")
    ]
    for band in bands:
        if (band.get("arcade_credit_spent_cents") or 0) > 0:
            raise errors.account_lien_outstanding()

    reservation["booking_status"] = "CHECKED_OUT"
    reservation["stay_status"] = "DEPARTED"
    reservation["checked_out_at"] = _db.now_iso()

    for band in engine.reservation_guest_bands(reservation_id):
        engine.mark_expired(band, "CHECKED_OUT")
        band["room_charge_enabled"] = False
        engine.decline_grants_for_band(band["id"], "RESERVATION_CLOSED")
        engine.recompute_arcade(band)

    common.recompute_pool_posture(resort_id)
    common.touch(reservation)
    return jsonify(response.success(common.serialise("reservation", reservation))), 200


@bp.route("/resorts/<resort_id>/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(resort_id, reservation_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "FrontDesk")
    reservation = linkres(resort_id, reservation_id)

    if reservation["booking_status"] != "RESERVED":
        raise errors.invalid_state()
    for band in engine.reservation_guest_bands(reservation_id):
        if band.get("wristband_status") in ("ISSUED", "ACTIVE"):
            raise errors.invalid_state(
                "A booking with live wristbands cannot be cancelled."
            )

    reservation["booking_status"] = "CANCELLED"
    reservation["stay_status"] = "DEPARTED"
    reservation["reserved_units"] = 0
    common.touch(reservation)
    return jsonify(response.success(common.serialise("reservation", reservation))), 200


def post_arcade_grant(resort_id, reservation, payload):
    band = common.fetch("wristband", v.required_str(payload, "wristband_id"), resort_id)
    amount = v.required_int(payload, "amount_cents")
    v.in_range(amount, "amount_cents", low=1)
    return _grant(band, reservation["id"], amount)


def _grant(band, reservation_id, amount):
    if not band.get("room_charge_enabled"):
        raise errors.room_charge_disabled()
    if amount > (band.get("arcade_credit_remaining_cents") or 0):
        raise errors.arcade_limit_exceeded()
    grant = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "wristband_id": band["id"],
        "reservation_id": reservation_id,
        "amount_cents": amount,
        "grant_status": "SUCCEEDED",
        "decline_reason": None,
    }
    _db.store().arcade_credit_grants[grant["id"]] = grant
    engine.recompute_arcade(band)
    return grant


@bp.route("/resorts/<resort_id>/reservations/<reservation_id>/arcade-credits", methods=["POST"])
def post_reservation_arcade_credit(resort_id, reservation_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_ARCADE)
    middleware.require(caller, "FrontDesk", "Anonymous")
    reservation = linkres(resort_id, reservation_id)
    grant = post_arcade_grant(resort_id, reservation, payload)
    return jsonify(response.success(common.serialise("arcade_credit_grant", grant))), 201


@bp.route("/resorts/<resort_id>/reservations/<reservation_id>/wristbands", methods=["GET"])
def list_reservation_wristbands(resort_id, reservation_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "AquaticsManager")
    linkres(resort_id, reservation_id)
    rows = [
        b for b in _db.store().wristbands.values()
        if b.get("reservation_id") == reservation_id and b.get("resort_id") == resort_id
    ]
    rows = common.created_at_sort(rows)
    data = common.serialise_many("wristband", rows)
    return jsonify(response.array(data, len(rows) or 1, 0, len(rows))), 200


@bp.route("/resorts/<resort_id>/reservations/<reservation_id>/activity-bookings", methods=["GET"])
def list_reservation_activity_bookings(resort_id, reservation_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    linkres(resort_id, reservation_id)
    rows = [
        b for b in _db.store().activity_bookings.values()
        if b.get("reservation_id") == reservation_id and b.get("resort_id") == resort_id
    ]
    rows = common.created_at_sort(rows)
    data = common.serialise_many("activity_booking", rows)
    return jsonify(response.array(data, len(rows) or 1, 0, len(rows))), 200