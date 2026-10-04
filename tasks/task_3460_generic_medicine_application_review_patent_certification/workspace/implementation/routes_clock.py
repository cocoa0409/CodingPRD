"""The logical clock test-driving endpoint, mounted OUTSIDE the API prefix."""
from flask import Blueprint

from auth import auth, require_role
from clock import fmt_instant, now, parse_instant, set_clock
from envelope import success_object
from errors import fail
from system_eval import on_clock_change
from validate import body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _uid, role = auth()
    require_role(role, ["ProgramAdmin"])
    b = body()
    raw = b.get("to_iso8601")
    try:
        target = parse_instant(raw)
    except ValueError:
        fail("ERR_INVALID_REQUEST",
             "to_iso8601 is required and must be an ISO 8601 instant")
    if target < now():
        fail("ERR_INVALID_REQUEST",
             "to_iso8601 must be at or after the current logical time")
    set_clock(target)
    on_clock_change()
    return success_object({"current_utc": fmt_instant(now())})
