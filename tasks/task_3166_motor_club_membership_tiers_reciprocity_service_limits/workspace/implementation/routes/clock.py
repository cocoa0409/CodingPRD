"""Logical clock endpoint: POST /motor-club/_clock/set_current_utc."""

from flask import Blueprint

from db import CLOCK, fmt_ts
from errors import invalid_request
from middleware import require_auth
from response import ok_obj
from services.calculations import membership_sweep, service_call_sweep
from services.validate import body_json, parse_iso_field

bp = Blueprint("clock", __name__)


@bp.post("/motor-club/_clock/set_current_utc")
def set_clock():
    require_auth({"ClubAdmin", "MemberServicesRep"})
    data = body_json()
    if "to_iso8601" not in data or data["to_iso8601"] is None:
        raise invalid_request("missing required field: to_iso8601")
    now = parse_iso_field(data["to_iso8601"], "to_iso8601")
    CLOCK.set(now)
    # advancing the clock fires the system sweeps in the same request
    membership_sweep(now)
    service_call_sweep(now)
    return ok_obj({"current_utc": fmt_ts(now)}, 200)
