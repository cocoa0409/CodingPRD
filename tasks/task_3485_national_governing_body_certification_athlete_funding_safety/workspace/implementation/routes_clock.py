"""POST /_clock/set_current_utc — unprefixed platform endpoint (PRD 2.5).

Deliberately mounted outside /api. CommitteeAdmin only. Sets the logical
clock and applies every due auto-transition.
"""
from flask import Blueprint, jsonify

import cascades
import timeutil
from validate import auth, body_json, req_datetime, require_roles

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = auth()
    require_roles(role, ["CommitteeAdmin"])
    body = body_json()
    target = req_datetime(body, "to_iso8601")
    timeutil.set_now(target)
    cascades.sweep_all(target)
    return jsonify({"current_utc": timeutil.now_iso()}), 200
