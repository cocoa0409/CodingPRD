"""Logical clock test-driving endpoint (PlatformAdmin only)."""
from flask import Blueprint

from db import clock_raw, set_clock
from middleware import actor, require_role
from response import ok_object
from validation import body_json, req_str, parse_iso_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = actor()
    require_role(role, ["PlatformAdmin"])
    data = body_json()
    current_utc = req_str(data, "current_utc")
    parse_iso_dt(current_utc, "current_utc")
    set_clock(current_utc)
    return ok_object({"current_utc": clock_raw()})
