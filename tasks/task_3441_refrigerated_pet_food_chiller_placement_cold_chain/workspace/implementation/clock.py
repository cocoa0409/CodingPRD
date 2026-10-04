"""Logical clock endpoint -- UNPREFIXED (lives outside /cold-chain per PRD 2.4)."""
from flask import Blueprint

from envelope import ok
from errors import ApiError
from state import fmt_dt, now, set_now
from validate import auth, body, fields, require_role

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = auth()
    v = fields(body(), [("to_iso8601", "dt", True, {})])
    require_role(role, ["PlatformAdmin"])
    target = v["to_iso8601"]
    if target <= now():
        raise ApiError("ERR_CLOCK_REGRESSION", 400,
                       "to_iso8601 must be strictly greater than the current logical time")
    set_now(target)
    return ok({"current_utc": fmt_dt(target)}, "object", 200)
