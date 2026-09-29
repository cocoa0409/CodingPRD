"""The logical clock endpoint (PRD 2.6)."""
from flask import Blueprint

import constants as C
from auth import endpoint
from envelope import ok
from errors import ApiError
from val import body, parse_instant
from services import clock as clock_svc

bp = Blueprint("clock", __name__, url_prefix=C.API_PREFIX)


@bp.post("/_clock/set_current_utc")
@endpoint(C.CARRIER_ROLES)
def set_current_utc():
    payload = body()
    raw = payload.get("to_iso8601")
    if raw is None:
        raise ApiError("ERR_VALIDATION", "to_iso8601 is required.")
    parsed = parse_instant(raw, "ERR_VALIDATION", "to_iso8601")
    return ok(clock_svc.set_clock(raw, parsed))
