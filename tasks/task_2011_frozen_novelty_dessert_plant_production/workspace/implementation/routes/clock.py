"""Logical clock (PRD §2.7): test-driving endpoint and time-based transitions."""

from flask import Blueprint

import db
from middleware import authenticate
from response import success_obj
from services import process_clock_transitions
from util import body_json, check_shape, parse_dt

bp = Blueprint("clock", __name__)

CLOCK_SPEC = {
    "to_iso8601": {"type": "datetime", "required": True},
}


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate({"PlantManager"})
    body = body_json()
    check_shape(body, CLOCK_SPEC)
    db.set_clock(parse_dt(body["to_iso8601"], "to_iso8601"))
    # Advancing the clock processes all time-based transitions whose trigger
    # instant has been reached (mix/lot/booking expiry, contract activation).
    process_clock_transitions()
    return success_obj({"current_utc": db.fmt_ts(db.now())})
