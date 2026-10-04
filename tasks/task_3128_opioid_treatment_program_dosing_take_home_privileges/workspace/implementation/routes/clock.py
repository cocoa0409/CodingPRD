"""POST /otp/_clock/set_current_utc — the logical clock (PRD 3.14)."""
from flask import Blueprint, request

import db
from errors import ApiError
from response import ok_object
from routes.common import context

bp = Blueprint("clock", __name__)


@bp.route("/otp/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    context(["ProgramAdministrator", "RegulatoryAuditor"])
    body = request.get_json(silent=True) or {}
    value = body.get("to_iso8601")
    parsed = db.parse_iso(value)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant")
    db.set_clock(parsed)
    return ok_object({"logical_clock_utc": db.fmt_dt(parsed)})