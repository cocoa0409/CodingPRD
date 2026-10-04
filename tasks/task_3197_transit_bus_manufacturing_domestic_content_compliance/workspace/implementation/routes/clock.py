"""Routes: logical clock."""
from flask import Blueprint
from db import DB, _parse_iso
from errors import err_invalid_request
from middleware import require_roles, get_body
from response import success_obj
from services.core import evaluate_time_transitions

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    body = get_body()
    to_iso8601 = body.get("to_iso8601")
    if to_iso8601 is None:
        raise err_invalid_request("Missing required field: to_iso8601")
    try:
        _parse_iso(to_iso8601)
    except Exception:
        raise err_invalid_request("Malformed to_iso8601")
    DB.clock.set(to_iso8601)
    evaluate_time_transitions()
    return success_obj({"now_iso8601": DB.clock.now_iso()})
