"""Test-driving endpoints: the logical clock (§2.10).

These are outside the public business surface and change no business state.
"""

from flask import Blueprint

import clock
from clock import ok, parse_dt
from request_context import actor, allowed, body, int_value

bp = Blueprint("test_driving", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    role, _ = actor()
    allowed(role, ["NetworkOperator"])
    payload = body(required=("current_utc",), optional=())
    clock.set_clock(parse_dt(payload["current_utc"], "current_utc"))
    return ok({"current_utc": clock.now_iso()})


@bp.post("/_test/advance_clock")
def advance_clock():
    role, _ = actor()
    allowed(role, ["NetworkOperator"])
    payload = body(required=("minutes",), optional=())
    minutes = int_value(payload["minutes"], "minutes")
    clock.advance_clock(minutes)
    return ok({"current_utc": clock.now_iso()})