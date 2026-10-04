"""Logical clock test-driving endpoint (PlatformAdmin only)."""

from flask import Blueprint

import db
from util import Body, canonical, get_context, require_role, success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _user_id, role = get_context()
    require_role(role, "PlatformAdmin")
    body = Body()
    to_dt = body.dt_f("to_iso8601", required=True)
    body.finalize()
    db.set_clock(to_dt)
    return success_object({"current_utc": canonical(db.now())})
