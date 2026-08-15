"""Logical clock endpoint."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    middleware.require_role("FraudOpsManager")
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    if not to_iso or not isinstance(to_iso, str):
        raise errors.err_invalid_request("to_iso8601 is required")
    try:
        db.set_clock(to_iso)
    except Exception:
        raise errors.err_invalid_request("to_iso8601 must be ISO 8601")
    domain.apply_time_based_transitions()
    return response.success({"current_utc": db.get_clock_iso()})
