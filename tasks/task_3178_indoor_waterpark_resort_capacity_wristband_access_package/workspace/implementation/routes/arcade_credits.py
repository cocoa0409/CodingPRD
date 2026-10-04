"""Arcade credit grant reads."""

from flask import Blueprint, jsonify

import db as _db
import middleware
import response
import validations as v
from services import common

bp = Blueprint("arcade_credits", __name__)


@bp.route("/resorts/<resort_id>/arcade-credits", methods=["GET"])
def list_grants(resort_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    common.get_resort(resort_id)
    limit, offset = v.query_pagination()
    scope_bands = {
        b["id"] for b in _db.store().wristbands.values()
        if b.get("resort_id") == resort_id
    }
    rows = [
        g for g in _db.store().arcade_credit_grants.values()
        if g.get("wristband_id") in scope_bands
    ]
    wristband_id = v.query_str("wristband_id")
    if wristband_id:
        rows = [g for g in rows if g.get("wristband_id") == wristband_id]
    reservation_id = v.query_str("reservation_id")
    if reservation_id:
        rows = [g for g in rows if g.get("reservation_id") == reservation_id]
    rows = common.created_at_sort(rows)
    window, total = common.paginate(rows, limit, offset)
    data = common.serialise_many("arcade_credit_grant", window)
    return jsonify(response.array(data, limit, offset, total)), 200


@bp.route("/resorts/<resort_id>/arcade-credits/<grant_id>", methods=["GET"])
def get_grant(resort_id, grant_id):
    caller = middleware.authenticate()
    middleware.require(caller, "platform_ops", "FrontDesk", "Group")
    common.get_resort(resort_id)
    grant = common.fetch("arcade_credit_grant", grant_id, resort_id)
    return jsonify(response.success(common.serialise("arcade_credit_grant", grant))), 200