"""Logical-clock test-driving endpoint (PRD §2.10)."""
from flask import Blueprint

from db import store
from middleware import authenticate
from middleware import ROLE_FINANCE_ADMIN as FA
from response import success
from services.domain import touch
from timeutil import parse_dt
from validation import body, req

bp = Blueprint("clock", __name__)


@bp.post("/robotics/_clock/set_current_utc")
def set_clock():
    authenticate({FA})
    b = body()
    new_clock = parse_dt(req(b, "to_iso8601"), "to_iso8601")
    store.logical_clock = new_clock
    # The single time-driven effect in the system: sessions still SCHEDULED
    # whose window has fully elapsed (clock past scheduled_end_utc) -> NO_SHOW.
    for s in store.sessions.values():
        if s["session_status"] != "SCHEDULED":
            continue
        end = parse_dt(s["scheduled_end_utc"], "scheduled_end_utc")
        if new_clock > end:
            s["session_status"] = "NO_SHOW"
            touch(s)
    return success({})
