"""POST /network/_clock/set_current_utc — logical clock control (NetworkOperator)."""

from flask import Blueprint

import db
from helpers import get_json, parse_iso, req_str
from middleware import require_roles
from response import iso3, ok

bp = Blueprint("clock", __name__)


@bp.post("/network/_clock/set_current_utc")
def set_clock():
    require_roles({"NetworkOperator"})
    body = get_json()
    dt = parse_iso(req_str(body, "to_iso8601"), "to_iso8601")
    db.set_clock(dt)
    return ok({"current_utc": iso3(db.get_clock())}, 200)
