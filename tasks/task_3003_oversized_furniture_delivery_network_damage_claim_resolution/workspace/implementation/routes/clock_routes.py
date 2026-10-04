"""Logical clock test-driving endpoint (NetworkAdmin only)."""
from flask import Blueprint, request

import clock
from middleware import require_roles
from response import success
from validation import get_body, req_datetime

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("NetworkAdmin")
def set_current_utc():
    body = get_body(request)
    new_time = req_datetime(body, "current_utc")
    clock.set_current(clock.format_dt(new_time))
    return success({"current_utc": clock.now_str()})
