"""Cabana inventory and cabana booking endpoints."""

from flask import Blueprint, jsonify

import db as _db
import errors
import middleware
import response
import validations as v
from db import HOLD_EXPIRY_ISO, parse_iso
from services import common, engine

bp = Blueprint("cabanas", __name__)

DECLARED_CABANA = ("cabana_label", "cabana_kind", "capacity_units")
DECLARED_BOOKING = (
    "cabana_id",
    "group_booking_id",
    "service_date",
    "start_minute",
    "end_minute",
    "member_units",
    "expected_cabana_version",
)

CABANA_KINDS = ("CABANA", "PARTY_ROOM")


def windows_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def live_bookings_for_cabana(resort_id, cabana_id):
    return [
        b for b in _db.store().cabana_bookings.values()
        if b.get("resort_id") == resort_id
        and b.get("cabana_id") == cabana_id
        and b.get("cabana_booking_status") in ("HELD", "BOOKED")
    ]


@bp.route("/resorts/<resort_id>/cabanas", methods=["POST"])
def create_cabana(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_CABANA)
    middleware.require(caller, "platform_ops")
    common.get_resort(resort_id)

    label = v.required_str(payload, "cabana_label")
    kind = v.in_enum(v.required_str(payload, "cabana_kind"), "cabana_kind", CABANA_KINDS)
    capacity_units = v.required_int(payload, "capacity_units")
    v.in_range(capacity_units, "capacity_units", low=1)

    for existing in _db.store().cabanas.values():
        if existing.get("resort_id") == resort_id and existing.get("cabana_label") == label:
            raise errors.invalid_request(
                "cabana_label must be unique within the property."
            )

    cabana = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "updated_at": _db.now_iso(),
        "version": 1,
        "resort_id": resort_id,
        "cabana_label": label,
        "cabana_kind": kind,
        "capacity_units": capacity_units,
        "cabana_status": "AVAILABLE",
    }
    _db.store().cabanas[cabana["id"]] = cabana
    return jsonify(response.success(common.serialise("cabana", cabana))), 201


@bp.route("/resorts/<resort_id>/cabanas", methods=["GET"])
def list_cabanas(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group", "Anonymous")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    rows = [
        c for c in _db.store().cabanas.values() if c.get("resort_id") == resort_id
    ]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("cabana", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/cabanas/<cabana_id>", methods=["GET"])
def get_cabana(resort_id, cabana_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group", "Anonymous")
    common.get_resort(resort_id)
    cabana = common.fetch("cabana", cabana_id, resort_id)
    return jsonify(response.success(common.serialise("cabana", cabana))), 200


@bp.route("/resorts/<resort_id>/cabanas/<cabana_id>/bookings", methods=["GET"])
def list_bookings_for_cabana(resort_id, cabana_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    common.get_resort(resort_id)
    common.fetch("cabana", cabana_id, resort_id)
    limit, offset = v.query_pagination()
    rows = [
        b for b in _db.store().cabana_bookings.values()
        if b.get("resort_id") == resort_id
        and b.get("cabana_id") == cabana_id
        and b.get("_persisted")
    ]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("cabana_booking", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/cabana-bookings", methods=["POST"])
def create_cabana_booking(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_BOOKING)
    middleware.require(caller, "Group", "FrontDesk")
    common.get_resort(resort_id)

    cabana = common.fetch("cabana", v.required_str(payload, "cabana_id"), resort_id)
    group_booking_id = v.required_str(payload, "group_booking_id")
    middleware.require_group_ownership(caller, group_booking_id)
    common.fetch("group_booking", group_booking_id, resort_id)

    service_date = v.required_service_date(payload, "service_date")
    start_minute = v.required_int(payload, "start_minute")
    v.in_range(start_minute, "start_minute", low=0, high=1439)
    end_minute = v.required_int(payload, "end_minute")
    if end_minute <= start_minute:
        raise errors.invalid_request("end_minute must be greater than start_minute.")
    v.in_range(end_minute, "end_minute", high=1440)
    member_units = v.required_int(payload, "member_units")
    v.in_range(member_units, "member_units", low=1)
    expected = v.required_int(payload, "expected_cabana_version")

    # PRD 2.9: a mismatched version is refused before any resource is created.
    if expected != cabana["version"]:
        raise errors.stale_cabana_version()

    if member_units > cabana["capacity_units"]:
        raise errors.cabana_units_unavailable()

    # PRD 2.4 orders the cabana window-overlap check above state admissibility:
    # a request that both clashes with a standing occupation and meets an
    # already-occupied cabana reports the overlap, not the occupation.
    for existing in live_bookings_for_cabana(resort_id, cabana["id"]):
        if existing.get("service_date") != service_date:
            continue
        if windows_overlap(
            start_minute, end_minute,
            existing.get("start_minute"), existing.get("end_minute"),
        ):
            raise errors.cabana_double_booked()

    if cabana["cabana_status"] != "AVAILABLE":
        raise errors.cabana_occupied()

    booking_id = _db.new_id()
    now = _db.now_iso()
    booking = {
        "id": booking_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "resort_id": resort_id,
        "cabana_id": cabana["id"],
        "group_booking_id": group_booking_id,
        "service_date": service_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "hold_expires_at": HOLD_EXPIRY_ISO,
        "members": [],
        "member_units": member_units,
        "cabana_booking_status": "HELD",
        "_persisted": True,
    }
    _db.store().cabana_bookings[booking_id] = booking
    cabana["cabana_status"] = "HELD"
    common.touch(cabana)
    return jsonify(response.array(
        [common.serialise("cabana_booking", booking)], 1, 0, 1
    )), 201


@bp.route("/resorts/<resort_id>/cabana-bookings", methods=["GET"])
def list_cabana_bookings(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    rows = [
        b for b in _db.store().cabana_bookings.values()
        if b.get("resort_id") == resort_id and b.get("_persisted")
    ]
    group_booking_id = v.query_str("group_booking_id")
    if group_booking_id:
        rows = [b for b in rows if b.get("group_booking_id") == group_booking_id]
    cabana_id = v.query_str("cabana_id")
    if cabana_id:
        rows = [b for b in rows if b.get("cabana_id") == cabana_id]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("cabana_booking", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/cabana-bookings/<cabana_booking_id>", methods=["GET"])
def get_cabana_booking(resort_id, cabana_booking_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    common.get_resort(resort_id)
    booking = common.fetch("cabana_booking", cabana_booking_id, resort_id)
    return jsonify(response.success(common.serialise("cabana_booking", booking))), 200


@bp.route("/resorts/<resort_id>/cabana-bookings/<cabana_booking_id>/confirm", methods=["POST"])
def confirm_cabana_booking(resort_id, cabana_booking_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "Group", "FrontDesk")
    common.get_resort(resort_id)
    booking = common.fetch("cabana_booking", cabana_booking_id, resort_id)
    middleware.require_group_ownership(caller, booking["group_booking_id"])

    if booking["cabana_booking_status"] != "HELD":
        raise errors.invalid_state()

    group = common.get("group_booking", booking["group_booking_id"])
    if group is None or group.get("group_status") != "CONFIRMED":
        raise errors.cabana_occupied()

    admitted = []
    for member in engine.members_for_group(booking["group_booking_id"]):
        if not member.get("checked_in"):
            member["checked_in"] = True
            admitted.append(member["id"])

    booking["members"] = admitted
    booking["cabana_booking_status"] = "BOOKED"
    booking["hold_expires_at"] = None
    booking["_persisted"] = True
    common.touch(booking)

    engine.recompute_group_reserved(group)

    cabana = common.get("cabana", booking["cabana_id"])
    if cabana is not None:
        cabana["cabana_status"] = "BOOKED"
        common.touch(cabana)

    return jsonify(response.success(common.serialise("cabana_booking", booking))), 200


@bp.route("/resorts/<resort_id>/cabana-bookings/<cabana_booking_id>/cancel", methods=["POST"])
def cancel_cabana_booking(resort_id, cabana_booking_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "Group", "FrontDesk", "platform_ops")
    common.get_resort(resort_id)
    booking = common.fetch("cabana_booking", cabana_booking_id, resort_id)
    middleware.require_group_ownership(caller, booking["group_booking_id"])

    if booking["cabana_booking_status"] not in ("HELD", "BOOKED"):
        raise errors.invalid_state()

    booking["cabana_booking_status"] = "CANCELLED"
    booking["members"] = []
    common.touch(booking)
    cabana = common.get("cabana", booking["cabana_id"])
    if cabana is not None:
        cabana["cabana_status"] = "AVAILABLE"
        common.touch(cabana)
    group = common.get("group_booking", booking["group_booking_id"])
    if group is not None:
        group["group_reserved_units"] = 0
        common.touch(group, mutate=False)
    return jsonify(response.success(common.serialise("cabana_booking", booking))), 200


@bp.route("/resorts/<resort_id>/cabana-bookings/<cabana_booking_id>/release", methods=["POST"])
def release_cabana_booking(resort_id, cabana_booking_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "platform_ops")
    common.get_resort(resort_id)
    booking = common.fetch("cabana_booking", cabana_booking_id, resort_id)

    cabana = common.get("cabana", booking["cabana_id"])
    if cabana is None or cabana.get("cabana_status") != "BOOKED":
        raise errors.cabana_occupied()
    if booking["cabana_booking_status"] != "BOOKED":
        raise errors.cabana_occupied()

    group = common.get("group_booking", booking["group_booking_id"])
    if group is not None:
        group["group_reserved_units"] = 0
        common.touch(group, mutate=False)
        # PRD 3.8: the admission unwind applies "when the released booking's
        # group is CONFIRMED and no other cabana booking in HELD or BOOKED
        # status still references that group".  The released booking is
        # excluded from that count - it is the occupation being unwound.
        others_live = any(
            other.get("id") != booking["id"]
            and other.get("cabana_booking_status") in ("HELD", "BOOKED")
            for other in engine.cabana_bookings_for_group(group["id"])
        )
        if group.get("group_status") == "CONFIRMED" and not others_live:
            for member in engine.members_for_group(group["id"]):
                if member.get("checked_in"):
                    member["checked_in"] = False

    booking["cabana_booking_status"] = "HELD"
    booking["members"] = []
    booking["hold_expires_at"] = HOLD_EXPIRY_ISO
    common.touch(booking)

    cabana["cabana_status"] = "HELD"
    common.touch(cabana)
    return jsonify(response.success(common.serialise("cabana_booking", booking))), 200


@bp.route("/resorts/<resort_id>/cabana-bookings/expire_holds", methods=["POST"])
def expire_holds(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "platform_ops")
    common.get_resort(resort_id)

    now = common.current_utc(resort_id)
    lapsed = []
    for booking in _db.store().cabana_bookings.values():
        if booking.get("resort_id") != resort_id:
            continue
        if booking.get("cabana_booking_status") != "HELD":
            continue
        expiry = parse_iso(booking.get("hold_expires_at"))
        if expiry is None or expiry > now:
            continue
        booking["cabana_booking_status"] = "EXPIRED"
        common.touch(booking)
        lapsed.append(booking)
        cabana = common.get("cabana", booking.get("cabana_id"))
        if cabana is not None:
            cabana["cabana_status"] = "AVAILABLE"
            common.touch(cabana)

    lapsed = common.created_at_sort(lapsed)
    data = common.serialise_many("cabana_booking", lapsed)
    return jsonify(response.array(data, len(data) or 1, 0, len(data))), 200