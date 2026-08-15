"""Logical clock endpoint (§2.6)."""
from flask import Blueprint, request
from middleware import require_roles
from response import success_object
from errors import invalid_request
from services import clock

bp = Blueprint("clock_routes", __name__)


@bp.route("/comp/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("CompAdmin")
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str) or not to_iso:
        raise invalid_request("to_iso8601 is required and must be an ISO 8601 string")
    try:
        new_value = clock.set_current(to_iso)
    except ValueError:
        raise invalid_request("to_iso8601 is not a well-formed ISO 8601 instant")
    return success_object({"current_utc": new_value})
