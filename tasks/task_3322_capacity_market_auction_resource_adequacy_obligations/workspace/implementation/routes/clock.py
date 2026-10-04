"""Logical clock test-driving endpoint."""
from flask import Blueprint

from db import db
from middleware import require_roles
from response import success_object, fmt_ts
from util import parse_dt, get_body, require_fields

bp = Blueprint("clock", __name__)


@bp.route("/capacity-market/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("MarketAdmin")
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_dt(body["to_iso8601"], "to_iso8601")
    db.clock.set_current(dt)
    return success_object({"current_utc": fmt_ts(db.clock.current())})
