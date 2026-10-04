"""Logical clock endpoint."""
from datetime import timezone

from flask import Blueprint

import db
from auth import require_roles
from response import ok_object
from util import body_json, parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/mlc/_clock/set_current_utc", methods=["POST"])
@require_roles("MLCAdministrator")
def set_clock(_user_id, _role):
    body = body_json(required=("to_iso8601",))
    dt = parse_iso(body["to_iso8601"], "to_iso8601")
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    db.set_now(dt)
    current = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return ok_object({"current_utc": current})
