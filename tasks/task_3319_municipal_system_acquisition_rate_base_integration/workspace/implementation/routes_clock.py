"""POST /_clock/set_current_utc — SystemAdmin only."""
from flask import Blueprint

from middleware import current_user, require_roles, require_fields, require_str
from response import success_obj, json_body
from errors import ApiError
from util import parse_iso, set_clock, iso_logical_clock

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = current_user()
    require_roles(role, ["SystemAdmin"])
    body = json_body()
    require_fields(body, ["to_iso8601"])
    raw = require_str(body, "to_iso8601")
    dt = parse_iso(raw)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "to_iso8601 must be an ISO 8601 timestamp")
    set_clock(dt)
    return success_obj({"current_utc": iso_logical_clock()})
