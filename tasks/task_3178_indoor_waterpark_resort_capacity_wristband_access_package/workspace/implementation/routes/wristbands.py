"""Wristband endpoints: issuance, activation, revocation, re-issuance, arcade."""

from flask import Blueprint, jsonify

import db as _db
import errors
import middleware
import response
import validations as v
from services import common, engine

bp = Blueprint("wristbands", __name__)

DECLARED_ISSUE = (
    "holder_type",
    "owner_name",
    "reservation_id",
    "day_pass_id",
    "group_member_id",
    "valid_on_service_date",
)
DECLARED_GRANT = ("amount_cents",)
DECLARED_REDEEM = ("wristband_id", "amount_cents")

HOLDER_TYPES = ("RESERVATION_GUEST", "DAY_PASS_GUEST", "GROUP_MEMBER")


@bp.route("/resorts/<resort_id>/wristbands", methods=["POST"])
def issue_wristband(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_ISSUE)
    middleware.require(caller, "platform_ops", "FrontDesk")
    resort = common.get_resort(resort_id)

    holder_type = v.in_enum(v.required_str(payload, "holder_type"), "holder_type", HOLDER_TYPES)
    owner_name = v.required_str(payload, "owner_name")
    reservation_id = v.optional_str(payload, "reservation_id")
    day_pass_id = v.optional_str(payload, "day_pass_id")
    group_member_id = v.optional_str(payload, "group_member_id")
    explicit_date = v.optional_service_date(payload, "valid_on_service_date")

    reservation = None
    day_pass = None
    valid_on = explicit_date

    if holder_type == "RESERVATION_GUEST":
        if reservation_id is None:
            raise errors.invalid_request("reservation_id is required for a reservation guest.")
        reservation = common.fetch("reservation", reservation_id, resort_id)
        if valid_on is None:
            valid_on = reservation["arrival_date"]
    elif holder_type == "DAY_PASS_GUEST":
        if day_pass_id is None:
            raise errors.invalid_request("day_pass_id is required for a day-pass guest.")
        day_pass = common.fetch("day_pass", day_pass_id, resort_id)
        if valid_on is None:
            valid_on = day_pass["service_date"]
    else:
        if group_member_id is None:
            raise errors.invalid_request("group_member_id is required for a group member.")
        member = common.fetch("group_member", group_member_id, resort_id)
        group = common.get("group_booking", member["group_booking_id"])
        if valid_on is None:
            valid_on = group["service_date"] if group else None

    room_charge_enabled = False
    limit_cents = 0
    if holder_type == "RESERVATION_GUEST" and reservation["stay_status"] == "IN_HOUSE":
        room_charge_enabled = True
        limit_cents = engine.arcade_credit_accrual(resort, reservation)

    band = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "updated_at": _db.now_iso(),
        "version": 1,
        "resort_id": resort_id,
        "holder_type": holder_type,
        "reservation_id": reservation_id,
        "day_pass_id": day_pass_id,
        "group_member_id": group_member_id,
        "owner_name": owner_name,
        "wristband_status": "ISSUED",
        "access_status": "PENDING",
        "room_charge_enabled": room_charge_enabled,
        "arcade_credit_limit_cents": limit_cents,
        "arcade_credit_spent_cents": 0,
        "arcade_credit_remaining_cents": limit_cents,
        "access_denied_reason": None,
        "valid_on_service_date": valid_on,
        "superseded_by_wristband_id": None,
    }
    _db.store().wristbands[band["id"]] = band
    return jsonify(response.success(common.serialise("wristband", band))), 201


@bp.route("/resorts/<resort_id>/wristbands", methods=["GET"])
def list_wristbands(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "AquaticsManager", "Anonymous")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    rows = [
        b for b in _db.store().wristbands.values() if b.get("resort_id") == resort_id
    ]
    holder_type = v.query_str("holder_type")
    if holder_type:
        rows = [b for b in rows if b.get("holder_type") == holder_type]
    for field in ("reservation_id", "day_pass_id", "superseded_by_wristband_id"):
        wanted = v.query_str(field)
        if wanted:
            rows = [b for b in rows if b.get(field) == wanted]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("wristband", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/wristbands/<wristband_id>", methods=["GET"])
def get_wristband(resort_id, wristband_id):
    caller = middleware.authenticate()
    middleware.require(
        caller, "platform_ops", "FrontDesk", "AquaticsManager", "GateAttendant", "Anonymous"
    )
    common.get_resort(resort_id)
    band = common.fetch("wristband", wristband_id, resort_id)
    return jsonify(response.success(common.serialise("wristband", band))), 200


@bp.route("/resorts/<resort_id>/wristbands/<wristband_id>/activate", methods=["POST"])
def activate_wristband(resort_id, wristband_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "FrontDesk", "GateAttendant")
    resort = common.get_resort(resort_id)
    band = common.fetch("wristband", wristband_id, resort_id)

    if band["wristband_status"] != "ISSUED":
        raise errors.wristband_not_active()

    if band["holder_type"] == "RESERVATION_GUEST":
        reservation = common.fetch("reservation", band.get("reservation_id"), resort_id)
        if reservation["stay_status"] != "IN_HOUSE":
            raise errors.invalid_state("The linked booking has not checked in.")
    elif band["holder_type"] == "DAY_PASS_GUEST":
        day_pass = common.fetch("day_pass", band.get("day_pass_id"), resort_id)
        if day_pass["day_pass_status"] != "RESERVED":
            raise errors.invalid_state("The linked day pass is not RESERVED.")

    if resort["pool_posture"] != "OPEN":
        raise errors.pool_closed()

    service_date = band["valid_on_service_date"]
    total = (
        common.room_units_reserved(resort_id, service_date)
        + common.group_units(resort_id, service_date)
        + common.day_pass_reserved_units(resort_id, service_date)
    )
    if total > resort["park_capacity_occupancy_units"]:
        raise errors.park_capacity_exceeded()

    band["wristband_status"] = "ACTIVE"
    band["access_status"] = "GRANTED"
    band["access_denied_reason"] = None
    common.touch(band)
    common.recompute_pool_posture(resort_id)
    return jsonify(response.success(common.serialise("wristband", band))), 200


@bp.route("/resorts/<resort_id>/wristbands/<wristband_id>/revoke", methods=["POST"])
def revoke_wristband(resort_id, wristband_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "FrontDesk", "AquaticsManager")
    common.get_resort(resort_id)
    band = common.fetch("wristband", wristband_id, resort_id)

    if band["wristband_status"] != "ACTIVE":
        raise errors.wristband_not_active()

    service_date = band["valid_on_service_date"]
    current = common.current_service_date(resort_id)
    begun = service_date is not None and service_date <= current
    if begun:
        presented = False
        for event in _db.store().admission_events.values():
            if event.get("wristband_id") != wristband_id:
                continue
            if event.get("service_date") != service_date:
                continue
            if event.get("direction") == "IN" and event.get("event_status") == "ACCEPTED":
                presented = True
                break
        if presented:
            raise errors.invalid_state(
                "A guest who has already entered the waterpark today cannot be revoked."
            )

    engine.revoke_band(band, None, "WRISTBAND_REVOKED")
    engine.refresh_attractions_after_band_change(resort_id)
    return jsonify(response.success(common.serialise("wristband", band))), 200


@bp.route("/resorts/<resort_id>/wristbands/<wristband_id>/reissue", methods=["POST"])
def reissue_wristband(resort_id, wristband_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, ())
    middleware.require(caller, "FrontDesk")
    resort = common.get_resort(resort_id)
    band = common.fetch("wristband", wristband_id, resort_id)

    if band["wristband_status"] != "ACTIVE":
        raise errors.wristband_not_active()
    if band.get("superseded_by_wristband_id") is not None:
        raise errors.wristband_already_reissued()
    if (band.get("arcade_credit_spent_cents") or 0) > 0:
        raise errors.held_units_not_releasable()

    service_date = band["valid_on_service_date"]
    total = (
        common.room_units_reserved(resort_id, service_date)
        + common.group_units(resort_id, service_date)
        + common.day_pass_reserved_units(resort_id, service_date)
    )
    if total > resort["park_capacity_occupancy_units"]:
        raise errors.park_capacity_exceeded()

    successor_id = _db.new_id()
    now = _db.now_iso()
    successor = {
        "id": successor_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "resort_id": resort_id,
        "holder_type": band["holder_type"],
        "reservation_id": band.get("reservation_id"),
        "day_pass_id": band.get("day_pass_id"),
        "group_member_id": band.get("group_member_id"),
        "owner_name": band["owner_name"],
        "wristband_status": "ISSUED",
        "access_status": "PENDING",
        "room_charge_enabled": False,
        "arcade_credit_limit_cents": band.get("arcade_credit_limit_cents") or 0,
        "arcade_credit_spent_cents": 0,
        "arcade_credit_remaining_cents": band.get("arcade_credit_limit_cents") or 0,
        "access_denied_reason": None,
        "valid_on_service_date": service_date,
        "superseded_by_wristband_id": None,
    }
    _db.store().wristbands[successor_id] = successor

    band["wristband_status"] = "REISSUED"
    band["access_status"] = "DENIED"
    band["room_charge_enabled"] = False
    band["arcade_credit_limit_cents"] = 0
    band["superseded_by_wristband_id"] = successor_id
    common.touch(band)
    engine.recompute_arcade(band)

    reservation = common.get("reservation", band.get("reservation_id"))
    if reservation is not None:
        reservation["reserved_units"] = reservation["waterpark_included_units"]
        common.touch(reservation, mutate=False)

    return jsonify(response.success(common.serialise("wristband", band))), 200


def grant_to_band(band, amount, reservation_id=None):
    if not band.get("room_charge_enabled"):
        raise errors.room_charge_disabled()
    if amount > (band.get("arcade_credit_remaining_cents") or 0):
        raise errors.arcade_limit_exceeded()
    grant = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "wristband_id": band["id"],
        "reservation_id": reservation_id if reservation_id is not None
        else band.get("reservation_id"),
        "amount_cents": amount,
        "grant_status": "SUCCEEDED",
        "decline_reason": None,
    }
    _db.store().arcade_credit_grants[grant["id"]] = grant
    engine.recompute_arcade(band)
    return grant


@bp.route("/resorts/<resort_id>/wristbands/<wristband_id>/arcade-grants", methods=["POST"])
def post_arcade_grant(resort_id, wristband_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_GRANT)
    middleware.require(caller, "FrontDesk", "Anonymous")
    common.get_resort(resort_id)
    band = common.fetch("wristband", wristband_id, resort_id)
    amount = v.required_int(payload, "amount_cents")
    v.in_range(amount, "amount_cents", low=1)
    grant = grant_to_band(band, amount)
    return jsonify(response.success(common.serialise("arcade_credit_grant", grant))), 201


@bp.route("/resorts/<resort_id>/wristbands/<wristband_id>/arcade-redeem", methods=["POST"])
def post_arcade_redeem(resort_id, wristband_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_REDEEM)
    middleware.require(caller, "FrontDesk")
    common.get_resort(resort_id)
    common.fetch("wristband", wristband_id, resort_id)
    band = common.fetch("wristband", v.required_str(payload, "wristband_id"), resort_id)
    amount = v.required_int(payload, "amount_cents")
    v.in_range(amount, "amount_cents", low=1)
    grant = grant_to_band(band, amount)
    return jsonify(response.success(common.serialise("arcade_credit_grant", grant))), 201


@bp.route("/resorts/<resort_id>/wristbands/<wristband_id>/arcade-credits", methods=["GET"])
def list_band_arcade_credits(resort_id, wristband_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    common.get_resort(resort_id)
    common.fetch("wristband", wristband_id, resort_id)
    limit, offset = v.query_pagination()
    rows = common.created_at_sort(engine.grants_for_band(wristband_id))
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("arcade_credit_grant", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/wristbands/<wristband_id>/successors", methods=["GET"])
def list_successors(resort_id, wristband_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk")
    common.get_resort(resort_id)
    band = common.fetch("wristband", wristband_id, resort_id)
    successor_id = band.get("superseded_by_wristband_id")
    rows = []
    if successor_id:
        successor = common.get("wristband", successor_id)
        if successor is not None and successor.get("resort_id") == resort_id:
            rows.append(successor)
    data = common.serialise_many("wristband", rows)
    return jsonify(response.array(data, len(rows) or 1, 0, len(rows))), 200