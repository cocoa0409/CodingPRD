"""POST /society/_clock/set_current_utc — test-driving logical clock."""

from flask import Blueprint

from cascade import run_time_sweep
from envelope import ok
from errors import ApiError, ERR_VALIDATION
from store import db, set_clock, parse_datetime
from validation import authenticate, require_role, payload

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = authenticate()
    require_role(role, {"SocietyAdmin"})
    body = payload()
    raw = body.get("to_iso8601")
    dt = parse_datetime(raw)
    if dt is None:
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'to_iso8601' is required and must be an ISO 8601 datetime.")
    set_clock(dt, raw)
    run_time_sweep()
    return ok({"current_utc": db.clock_raw}, 200)
