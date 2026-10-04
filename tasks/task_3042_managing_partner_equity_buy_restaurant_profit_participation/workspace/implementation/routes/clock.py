"""Logical clock routes (PRD §2.4)."""

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from services import sweeps
from util import get_json_body, parse_datetime, req_field

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("PlatformAdmin")
    body = get_json_body()
    current = parse_datetime(req_field(body, "current_utc"), "current_utc")
    db.set_clock(current)
    applied = sweeps.run_sweeps()
    return success_object({
        "current_utc": current.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "sweeps_applied": applied,
    })
