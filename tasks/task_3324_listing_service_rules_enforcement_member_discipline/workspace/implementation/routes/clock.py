"""Logical clock endpoints (AssociationStaff only)."""

from flask import Blueprint

import services
from auth import require_roles
from db import store, now_iso, set_clock, advance_days
from errors import raise_err, ERR_INVALID_REQUEST
from helpers import body, parse_dt
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/mls/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("AssociationStaff")
    data = body()
    to_iso8601 = data.get("to_iso8601")
    if not to_iso8601:
        raise_err(ERR_INVALID_REQUEST, "Missing required field 'to_iso8601'")
    dt = parse_dt(to_iso8601, "to_iso8601")
    set_clock(dt)
    services.evaluate_clock_triggers()
    return success_object({"now_iso8601": now_iso()})


@bp.route("/mls/_clock/advance_day", methods=["POST"])
def advance_day():
    require_roles("AssociationStaff")
    data = body()
    days = data.get("days", 1)
    if isinstance(days, bool) or not isinstance(days, int) or days < 0:
        raise_err(ERR_INVALID_REQUEST, "days must be a non-negative integer")
    advance_days(days)
    services.evaluate_clock_triggers()
    return success_object({"now_iso8601": now_iso()})
