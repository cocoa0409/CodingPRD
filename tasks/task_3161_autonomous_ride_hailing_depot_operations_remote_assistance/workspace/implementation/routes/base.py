"""Envelope probes: the liveness check and the logical clock setter."""

from flask import Blueprint, request

from db import format_utc, store
from middleware import ANY, authenticate, authorize, body_object, require_instant
from response import success_object

bp = Blueprint("base", __name__)


@bp.get("/fleet/health")
def health():
    caller = authenticate(request.headers)
    authorize(caller, ANY)
    return success_object({"status": "ok", "service": "autonomous-ride-hailing-depot-ops"})


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    caller = authenticate(request.headers)
    authorize(caller, ANY)
    body = body_object(request.get_json(silent=True))
    current_utc = require_instant(body, "current_utc")
    store.clock.set(current_utc)
    return success_object({"current_utc": format_utc(store.now())})