"""Logical clock control route."""
from flask import Blueprint, request
from db import store, clock, parse_iso, fmt_iso
from errors import fail
from response import success_object
from middleware import authenticate, require_role
import services as svc

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    role, _uid = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = request.get_json(silent=True) or {}
    target = parse_iso(body.get("to_iso8601"))
    if target is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO8601 timestamp")
    with store.lock:
        clock.set(target)
        svc.clock_advanced()
    return success_object({"now": fmt_iso(clock.now())})
