"""The logical-clock control endpoint (PRD section 2.6).

This is the one resource outside the /records-desk prefix.
"""
from flask import Blueprint

import clock
import response
import validation as v
from middleware import ALL_ROLES, authenticate

bp = Blueprint("clock_control", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(ALL_ROLES)
    payload = v.body()
    to_iso8601 = v.field_instant(payload, "to_iso8601")
    clock.set_now(to_iso8601)
    return response.object_response({"current_utc": clock.now_iso()})
