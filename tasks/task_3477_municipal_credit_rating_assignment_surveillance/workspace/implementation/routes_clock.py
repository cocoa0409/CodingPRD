"""Logical clock endpoint (PRD §2.4) — mounted OUTSIDE the /muni prefix."""
from flask import Blueprint

from auth import auth
from constants import ROLE_PLATFORM_ADMIN
from envelope import success_object
from services_sweep import run_sweep
from store import db
from validators import body, require_datetime, require_fields

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth([ROLE_PLATFORM_ADMIN])
    payload = body()
    require_fields(payload, ["to_iso8601"])
    target = require_datetime(payload, "to_iso8601")
    db.set_clock(target)
    run_sweep()
    return success_object({}, status=200)
