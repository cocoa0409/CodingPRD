"""Clock endpoints: POST /compliance/_clock/set_current_utc, /advance."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import err_invalid_request
from helpers import parse_dt
from middleware import require_roles
from response import fmt_ts, success_object
from services import advance_sweep, restriction_sweep_all

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("RegionalEntityReviewer")
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    if to_iso is None:
        raise err_invalid_request("to_iso8601 is required")
    db.clock = parse_dt(to_iso, "to_iso8601")
    # setting the clock also re-evaluates restriction posture
    restriction_sweep_all()
    return success_object({"now": fmt_ts(db.clock)})


@bp.post("/_clock/advance")
def advance_clock():
    require_roles("RegionalEntityReviewer")
    body = request.get_json(silent=True) or {}
    seconds = body.get("seconds")
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        raise err_invalid_request("seconds must be a number")
    db.clock = db.clock + timedelta(seconds=seconds)
    advance_sweep()
    return success_object({"now": fmt_ts(db.clock)})
