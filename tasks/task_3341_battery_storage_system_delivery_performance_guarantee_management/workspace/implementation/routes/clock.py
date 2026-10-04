"""Logical clock route: POST /_clock/set_current_utc (PlatformAdmin)."""
from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import success_object, iso_utc
from util import parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles({"PlatformAdmin"})
def set_clock():
    body = request.get_json(silent=True) or {}
    dt = parse_iso(body.get("to_iso8601"), "to_iso8601")
    store.set_clock(dt)
    return success_object({"current_utc": iso_utc(store.clock())})
