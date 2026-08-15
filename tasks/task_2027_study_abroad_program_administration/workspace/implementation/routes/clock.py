"""Logical clock test-driving endpoint."""

from flask import Blueprint, request
import db
from middleware import get_auth, require_role
from response import success_object
from utils import require_string, parse_dt
from middleware import STAFF_ROLES

bp = Blueprint("clock", __name__)


@bp.route("/api/v1/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    user_id, role = get_auth()
    require_role(role, list(STAFF_ROLES))

    body = request.get_json(silent=True) or {}
    to_iso8601 = require_string(body, "to_iso8601")
    parse_dt(to_iso8601, "to_iso8601")  # validate format

    current = db.set_clock(to_iso8601)
    return success_object({"current_utc": current}, 200)
