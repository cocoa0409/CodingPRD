"""Group bookings: creation, deposits, confirmation, cancellation and reads."""

from datetime import timedelta

from flask import Blueprint, jsonify

import db as _db
import errors
import middleware
import response
import validations as v
from db import date_from_service_date
from services import common, engine

bp = Blueprint("group_bookings", __name__)

DECLARED_CREATE = ("group_kind", "service_date", "member_count", "deposit_paid_cents")
DECLARED_DEPOSIT = ("amount_cents", "external_payment_ref")

GROUP_KINDS = ("BIRTHDAY", "SCHOOL", "FAMILY_REUNION", "CORPORATE")


def horizon_check(resort_id, service_date):
    current = date_from_service_date(common.current_service_date(resort_id))
    requested = date_from_service_date(service_date)
    if requested > current + timedelta(days=common.SERVICE_DATE_HORIZON_DAYS):
        raise errors.service_date_out_of_range()


def fetch_group(resort_id, group_booking_id):
    common.get_resort(resort_id)
    return common.fetch("group_booking", group_booking_id, resort_id)


@bp.route("/resorts/<resort_id>/group-bookings", methods=["POST"])
def create_group_booking(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_CREATE)
    middleware.require(caller, "Group", "FrontDesk")
    common.get_resort(resort_id)

    group_kind = v.in_enum(
        v.required_str(payload, "group_kind"), "group_kind", GROUP_KINDS
    )
    service_date = v.required_service_date(payload, "service_date")
    member_count = v.required_int(payload, "member_count")
    deposit_paid = v.optional_int(payload, "deposit_paid_cents", 0)
    if deposit_paid is None:
        deposit_paid = 0

    horizon_check(resort_id, service_date)

    if group_kind == "BIRTHDAY" and member_count < common.BIRTHDAY_PARTY_MINIMUM_MEMBERS:
        raise errors.group_minimum_not_met()

    if member_count < 1:
        raise errors.invalid_request("member_count must be at least 1.")

    group_booking_id = _db.new_id()
    middleware.require_group_ownership(caller, group_booking_id)

    now = _db.now_iso()
    group = {
        "id": group_booking_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "resort_id": resort_id,
        "group_kind": group_kind,
        "group_status": "PENDING_DEPOSIT",
        "service_date": service_date,
        "member_count": member_count,
        "deposit_paid_cents": deposit_paid,
        "group_reserved_units": 0,
    }
    _db.store().group_bookings[group_booking_id] = group
    return jsonify(response.success(common.serialise("group_booking", group))), 201


@bp.route("/resorts/<resort_id>/group-bookings", methods=["GET"])
def list_group_bookings(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    rows = [
        g for g in _db.store().group_bookings.values() if g.get("resort_id") == resort_id
    ]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("group_booking", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/group-bookings/<group_booking_id>", methods=["GET"])
def get_group_booking(resort_id, group_booking_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    group = fetch_group(resort_id, group_booking_id)
    return jsonify(response.success(common.serialise("group_booking", group))), 200


@bp.route("/resorts/<resort_id>/group-bookings/<group_booking_id>/deposits", methods=["POST"])
def record_deposit(resort_id, group_booking_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_DEPOSIT)
    middleware.require(caller, "Group", "FrontDesk")
    common.get_resort(resort_id)
    middleware.require_group_ownership(caller, group_booking_id)
    group = common.fetch("group_booking", group_booking_id, resort_id)

    amount = v.required_int(payload, "amount_cents")
    v.in_range(amount, "amount_cents", low=1)
    reference = v.required_str(payload, "external_payment_ref")

    requirement = group["member_count"] * common.GROUP_DEPOSIT_PER_MEMBER_CENTS
    if group["deposit_paid_cents"] + amount < requirement:
        raise errors.payment_declined()

    outcome = _db.store().gateway_outcomes.pop(group_booking_id, None)
    if outcome is not None and outcome != "ACCEPTED":
        raise errors.declined_authorization()

    group["deposit_paid_cents"] += amount
    group["last_payment_ref"] = reference
    common.touch(group)
    return jsonify(response.success(common.serialise("group_booking", group))), 201


@bp.route("/resorts/<resort_id>/group-bookings/<group_booking_id>/confirm", methods=["POST"])
def confirm_group_booking(resort_id, group_booking_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "Group", "FrontDesk")
    common.get_resort(resort_id)
    middleware.require_group_ownership(caller, group_booking_id)
    group = common.fetch("group_booking", group_booking_id, resort_id)

    if group["group_status"] != "PENDING_DEPOSIT":
        raise errors.invalid_state()

    requirement = group["member_count"] * common.GROUP_DEPOSIT_PER_MEMBER_CENTS
    if group["deposit_paid_cents"] < requirement:
        raise errors.invalid_state("The deposit condition is not met.")

    group["group_status"] = "CONFIRMED"
    common.touch(group)
    return jsonify(response.success(common.serialise("group_booking", group))), 200


@bp.route("/resorts/<resort_id>/group-bookings/<group_booking_id>/cancel", methods=["POST"])
def cancel_group_booking(resort_id, group_booking_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "Group", "platform_ops")
    common.get_resort(resort_id)
    middleware.require_group_ownership(caller, group_booking_id)
    group = common.fetch("group_booking", group_booking_id, resort_id)

    if group["group_status"] not in ("PENDING_DEPOSIT", "CONFIRMED"):
        raise errors.invalid_state()

    group["group_status"] = "CANCELLED"
    group["group_reserved_units"] = 0

    for booking in engine.cabana_bookings_for_group(group_booking_id):
        if booking.get("cabana_booking_status") not in ("HELD", "BOOKED"):
            continue
        booking["cabana_booking_status"] = "CANCELLED"
        common.touch(booking)
        cabana = common.get("cabana", booking.get("cabana_id"))
        if cabana is not None:
            cabana["cabana_status"] = "AVAILABLE"
            common.touch(cabana)

    for booking in _db.store().activity_bookings.values():
        if booking.get("group_booking_id") != group_booking_id:
            continue
        if booking.get("activity_booking_status") in ("PENDING_PAYMENT", "CONFIRMED"):
            booking["activity_booking_status"] = "CANCELLED"
            common.touch(booking)

    common.touch(group)
    return jsonify(response.success(common.serialise("group_booking", group))), 200


@bp.route("/resorts/<resort_id>/group-bookings/<group_booking_id>/members", methods=["GET"])
def list_group_members(resort_id, group_booking_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    fetch_group(resort_id, group_booking_id)
    rows = common.created_at_sort(engine.members_for_group(group_booking_id))
    data = common.serialise_many("group_member", rows)
    return jsonify(response.array(data, len(rows) or 1, 0, len(rows))), 200


@bp.route("/resorts/<resort_id>/group-bookings/<group_booking_id>/cabana-bookings", methods=["GET"])
def list_group_cabana_bookings(resort_id, group_booking_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    fetch_group(resort_id, group_booking_id)
    if caller.is_group:
        middleware.require_group_ownership(caller, group_booking_id)
    rows = common.created_at_sort(engine.cabana_bookings_for_group(group_booking_id))
    rows = [b for b in rows if b.get("_persisted")]
    data = common.serialise_many("cabana_booking", rows)
    return jsonify(response.array(data, len(rows) or 1, 0, len(rows))), 200


@bp.route("/resorts/<resort_id>/group-bookings/<group_booking_id>/activity-bookings", methods=["GET"])
def list_group_activity_bookings(resort_id, group_booking_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    fetch_group(resort_id, group_booking_id)
    rows = [
        b for b in _db.store().activity_bookings.values()
        if b.get("group_booking_id") == group_booking_id
    ]
    rows = common.created_at_sort(rows)
    data = common.serialise_many("activity_booking", rows)
    return jsonify(response.array(data, len(rows) or 1, 0, len(rows))), 200


@bp.route("/resorts/<resort_id>/group-bookings/<group_booking_id>/admissions", methods=["GET"])
def list_group_admissions(resort_id, group_booking_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    fetch_group(resort_id, group_booking_id)
    limit, offset = v.query_pagination()
    member_ids = {m["id"] for m in engine.members_for_group(group_booking_id)}
    band_ids = {
        b["id"] for b in _db.store().wristbands.values()
        if b.get("group_member_id") in member_ids
    }
    rows = [
        e for e in _db.store().admission_events.values()
        if e.get("resort_id") == resort_id and e.get("wristband_id") in band_ids
    ]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("admission_event", window)
    return jsonify(response.array(data, limit, offset, total)), 200