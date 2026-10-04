"""Test-driving capability: the logical clock."""
from flask import Blueprint

from store import get_clock, set_clock
from helpers import body, need, ok, parse_dt_val, fmt_dt, require_roles

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc():
    b = body()
    ts = parse_dt_val(need(b, "to_iso8601"))
    set_clock(ts)
    return ok({"current_utc": fmt_dt(get_clock())})
