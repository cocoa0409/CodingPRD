"""Logical clock endpoint (PlatformAdmin only)."""
from flask import Blueprint

from auth import context, require_roles
from envelope import fmt_dt, get_body, req_dt, success
from store import get_clock, set_clock

bp = Blueprint("clock", __name__)


@bp.post("/drinkware/_clock/set_current_utc")
def set_current_utc():
    _, role = context()
    require_roles(role, ["PlatformAdmin"])
    body = get_body()
    dt = req_dt(body, "to_iso8601")
    set_clock(dt)
    return success({"current_utc": fmt_dt(get_clock())})
