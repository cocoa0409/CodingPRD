from flask import Blueprint, request

from db import set_clock, format_iso, clock_now
from middleware import get_user_context, require_roles, get_json_body
from response import success_object
from services.common import parse_datetime_value

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    get_user_context()
    body = get_json_body()
    to_iso = parse_datetime_value(body.get("to_iso8601"), "to_iso8601")
    require_roles("SystemAdmin")
    set_clock(to_iso)
    return success_object({"current_utc": format_iso(clock_now())})
