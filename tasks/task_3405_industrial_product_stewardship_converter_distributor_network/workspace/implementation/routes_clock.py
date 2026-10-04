"""Logical clock test-driving endpoint (PRD §2.4)."""

from flask import Blueprint

import auth
import envelope
import store
import validation
from errors import invalid_request

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _user_id, role = auth.authenticate()
    auth.require_role(role, ["PlatformAdmin"])
    payload = validation.get_payload()
    raw = validation.req_str(payload, "current_utc")
    dt = store.parse_dt(raw)
    if dt is None:
        raise invalid_request("current_utc must be an ISO 8601 UTC timestamp")
    store.set_clock(dt)
    return envelope.success_object({"current_utc": raw}, 200)
