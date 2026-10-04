"""Test-driving clock endpoint."""
from flask import Blueprint, request

import clock
import db
import errors as E
from response import success_object
from util import parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    body = request.get_json(silent=True) or {}
    to = body.get("to_iso8601")
    if to is None:
        raise E.err(E.ERR_INVALID_REQUEST, "Missing required field: to_iso8601")
    dt = parse_iso(to, "to_iso8601")
    clock.set_now(dt)
    return success_object({"current_utc": db.format_ts(clock.now())}, status=200)
