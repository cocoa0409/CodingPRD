"""Logical clock endpoint."""

from flask import Blueprint, request

from cascades import clock_sweep
from db import store
from middleware import require_roles
from models import fmt_iso, parse_iso, require_field
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles({"FleetAdmin"})
    body = request.get_json(silent=True) or {}
    to_iso8601 = require_field(body, "to_iso8601")
    dt = parse_iso(to_iso8601, "to_iso8601")
    store.clock = dt
    clock_sweep()
    return success_object({"current_utc": fmt_iso(store.clock)})
