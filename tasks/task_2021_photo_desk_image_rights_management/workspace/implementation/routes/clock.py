"""Logical clock endpoint."""

from flask import Blueprint, request
from db import set_logical_now, logical_now, parse_iso, iso_now_str
from errors import ApiError, ERR_INVALID_REQUEST
from response import success_object
from middleware import get_auth, require_role

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = get_auth()
    require_role(role, {"PlatformAdmin"})

    body = request.get_json(force=True, silent=True) or {}
    to_iso8601 = body.get("to_iso8601")
    if not to_iso8601 or not isinstance(to_iso8601, str):
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 is required", 400)

    dt = parse_iso(to_iso8601)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 datetime", 400)

    set_logical_now(dt)
    return success_object({"current_utc": iso_now_str(dt)})
