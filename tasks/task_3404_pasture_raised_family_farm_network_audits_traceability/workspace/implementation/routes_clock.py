"""Logical clock test-driving endpoint (PRD 2.5).

POST /farm-network/_clock/set_current_utc   (PlatformAdmin, 200)

The new instant must be strictly after the current one (monotonic); advancing
fires, in order: audit expiry, corrective-action overdue + severity
escalations, and certification lapse re-derivation.
"""
from flask import Blueprint

import clock
import domain
from auth import authenticate, authorize
from errors import ApiError
from responses import ok
from validation import get_body, f_datetime

bp = Blueprint("clock", __name__, url_prefix="/farm-network")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    uid, role = authenticate()
    authorize(role, ("PlatformAdmin",))
    data = get_body()
    raw, target = f_datetime(data, "to_iso8601")
    if target <= clock.now():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "to_iso8601 must be strictly after the current logical instant")
    clock.set_current(target)
    domain.run_clock_sweeps()
    return ok({"current_utc": clock.iso_ms(clock.now())})
