# Test-driving logical clock (PRD 2.5).
from flask import Blueprint

from auth import require_roles
from envelope import success
from store import store
from sweep import run_sweep
from validate import check_unknown_fields, get_body, require_fields
from timeutil import parse_iso
from errors import ERR_INVALID_REQUEST, ApiError

bp = Blueprint("clock", __name__)

_ALLOWED = {"to_iso8601"}


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("PlatformAdmin")
    body = get_body(required=True)
    require_fields(body, ["to_iso8601"])
    check_unknown_fields(body, _ALLOWED)
    raw = body["to_iso8601"]
    try:
        target = parse_iso(raw)
    except (ValueError, OverflowError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO8601 datetime string")
    store.clock = target
    run_sweep()
    # Echo the accepted reading.
    return success({"current_utc": raw})
