"""Logical clock endpoint (PRD 2.5)."""

from flask import Blueprint, request

import db
import response as resp
import services
import validators as V
from middleware import authorize, ALL_ROLES

bp = Blueprint("clock", __name__)


@bp.route("/dough-ops/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorize(*ALL_ROLES)
    data = V.body_json(request)
    raw = data.get("to_iso8601")
    dt = V.parse_instant(raw, "to_iso8601")
    db.set_clock(raw if isinstance(raw, str) else db.fmt_instant(dt), dt)
    services.sweep_autolock()
    return resp.object_response({"now_iso8601": db.fmt_instant(dt)}, 200)
