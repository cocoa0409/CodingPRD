"""Logical clock test-driving endpoint (PRD 2.4) -- outside the /smelter-ops prefix."""
from flask import Blueprint

from auth import require_roles
from db import set_logical_clock
from envelope import ok_object
from util import as_datetime, fmt_iso, get_body, req

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc():
    body = get_body()
    target = as_datetime(req(body, "to_iso8601"), "to_iso8601")
    set_logical_clock(target)
    return ok_object({"current_utc": fmt_iso(target)})
