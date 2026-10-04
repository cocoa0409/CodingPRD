"""POST /_clock/set_current_utc — platform-level logical clock endpoint.

Deliberately UNPREFIXED: it lives outside the /ptab api_prefix (PRD 2.4).
"""

from flask import Blueprint

from db import store, parse_iso
from errors import raise_err, ERR_VALIDATION
from helpers import require_roles, get_body, req_string, success_object

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("PlatformAdmin")
    body = get_body()
    to_iso8601 = req_string(body, "to_iso8601")
    try:
        parse_iso(to_iso8601)
    except (ValueError, TypeError):
        raise_err(ERR_VALIDATION, "to_iso8601 must be a valid ISO 8601 datetime")
    current_utc = store.clock.set(to_iso8601)
    return success_object({"current_utc": current_utc}, status=200)
