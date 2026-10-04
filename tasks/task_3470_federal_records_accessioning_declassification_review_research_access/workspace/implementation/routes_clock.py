"""The logical-clock endpoint (PRD §2.4) — deliberately UNPREFIXED.

POST /_clock/set_current_utc   PlatformAdmin, 200, {"current_utc": ...}

This endpoint lives outside the /records mount. The startup default before any
call is exactly 2026-09-01T00:00:00Z and the clock never falls back to
wall-clock time.
"""
from flask import Blueprint

from envelope import ok_object
from errors import err
from store import DB, parse_dt, tsc
from validation import get_auth, get_body, require_role

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _uid, role = get_auth()                       # rung 1
    require_role(role, ["PlatformAdmin"])         # rung 2
    body = get_body()
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str) or to_iso8601 == "":
        raise err(
            "ERR_INVALID_REQUEST",
            "to_iso8601 is required and must be an ISO 8601 UTC timestamp",
        )
    try:
        dt = parse_dt(to_iso8601)
    except Exception:
        raise err(
            "ERR_INVALID_REQUEST",
            "to_iso8601 must be an ISO 8601 UTC timestamp",
        )
    DB.set_clock(dt)
    return ok_object({"current_utc": tsc(DB.now())})
