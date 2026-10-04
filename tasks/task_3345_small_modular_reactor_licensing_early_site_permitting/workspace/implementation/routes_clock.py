"""Logical clock test-driving endpoint."""
from flask import Blueprint

from rbac import require_role
from routes_permits import run_hearing_expiry_sweep
from store import iso_ms, set_clock, success_object
from validation import json_body, v_iso

bp = Blueprint("clock", __name__, url_prefix="/licensing")


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_role("DoeProgram")
    body = json_body()
    to_dt = v_iso(body, "to_iso8601")
    set_clock(to_dt)
    run_hearing_expiry_sweep()
    return success_object({"current_utc": iso_ms(to_dt)})
