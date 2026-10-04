"""Group member registration and reads."""

from flask import Blueprint, jsonify

import db as _db
import middleware
import response
import validations as v
from services import common

bp = Blueprint("group_members", __name__)

DECLARED_CREATE = ("group_booking_id", "member_name", "member_units")


@bp.route("/resorts/<resort_id>/group-members", methods=["POST"])
def create_group_member(resort_id):
    caller = middleware.authenticate()
    payload = v.body()
    v.reject_undeclared(payload, DECLARED_CREATE)
    middleware.require(caller, "Group", "FrontDesk")
    common.get_resort(resort_id)

    group_booking_id = v.required_str(payload, "group_booking_id")
    common.get_resort(resort_id)
    middleware.require_group_ownership(caller, group_booking_id)
    common.fetch("group_booking", group_booking_id, resort_id)

    member_name = v.required_str(payload, "member_name")
    member_units = v.optional_int(payload, "member_units", 1)
    if member_units is None:
        member_units = 1
    v.in_range(member_units, "member_units", low=1)

    member = {
        "id": _db.new_id(),
        "created_at": _db.now_iso(),
        "group_booking_id": group_booking_id,
        "member_name": member_name,
        "member_units": member_units,
        "checked_in": False,
    }
    _db.store().group_members[member["id"]] = member
    return jsonify(response.success(common.serialise("group_member", member))), 201


@bp.route("/resorts/<resort_id>/group-members", methods=["GET"])
def list_group_members(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    group_ids = {
        g["id"] for g in _db.store().group_bookings.values()
        if g.get("resort_id") == resort_id
    }
    rows = [
        m for m in _db.store().group_members.values()
        if m.get("group_booking_id") in group_ids
    ]
    group_booking_id = v.query_str("group_booking_id")
    if group_booking_id:
        rows = [m for m in rows if m.get("group_booking_id") == group_booking_id]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("group_member", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/group-members/<group_member_id>", methods=["GET"])
def get_group_member(resort_id, group_member_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    common.get_resort(resort_id)
    member = common.fetch("group_member", group_member_id, resort_id)
    return jsonify(response.success(common.serialise("group_member", member))), 200