"""Logical clock and probe endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import authenticate, require_roles
from response import success_object
from services_common import parse_datetime, fmt_ts

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth = authenticate()
    require_roles(auth, {"BureauCompliance"})
    body = request.get_json(silent=True) or {}
    current_utc = body.get("current_utc")
    if current_utc is None:
        raise errors.invalid_request("current_utc is required")
    dt = parse_datetime(current_utc)
    if dt is None:
        raise errors.invalid_request("current_utc is not a valid datetime")
    store.clock = dt
    return success_object({"current_utc": fmt_ts(dt)})


@bp.route("/_probe/no-auth", methods=["GET"])
def probe_no_auth():
    auth = authenticate()
    require_roles(auth, {"BureauCompliance"})
    return success_object({"ok": True})
