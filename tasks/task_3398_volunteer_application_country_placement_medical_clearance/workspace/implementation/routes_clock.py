"""Test-driving logical clock: POST /_clock/set_current_utc runs the sweep."""
from flask import Blueprint, request

from authz import auth, require_roles
from cascade import clock_sweep
from db import fmt_ts, logical_now, set_logical_clock, ts_sec
from errors import err, ok_object
from validate import as_dt, body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth()
    require_roles(request.headers.get("X-User-Role"), ("SystemAdmin",))
    data = body()
    target = as_dt(data, "to_iso8601")
    # The clock must never move backwards (re-setting the same instant is
    # allowed and re-runs the sweep, which is idempotent).
    if ts_sec(target) < ts_sec(logical_now()):
        err("ERR_VALIDATION", 400, "The logical clock must not move backwards")
    set_logical_clock(target)
    clock_sweep(target)
    return ok_object({"current_utc": fmt_ts(logical_now())})
