"""Logical clock test-driving endpoint (PRD 2.4). Forward-only."""
from flask import Blueprint

from auth import authenticate
from db import clock_now, fmt_clock, set_clock
from envelope import ok
from errors import raise_err
from validate import get_body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(("WorkshopManager",))
    body = get_body()
    dt = req_dt(body, "to_iso8601")
    if dt < clock_now():
        raise_err("ERR_CLOCK_REGRESSION", "the logical clock may only move forward")
    set_clock(dt)
    return ok({"current_utc": fmt_clock(dt)})
