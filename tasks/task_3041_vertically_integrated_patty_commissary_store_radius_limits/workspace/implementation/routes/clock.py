"""Logical clock admin endpoint."""

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from util import get_json_body, parse_datetime, req_field

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("SupplyChainDirector")
    body = get_json_body()
    current_utc = req_field(body, "current_utc")
    dt = parse_datetime(current_utc, "current_utc")
    db.set_clock(dt)
    # Echo the accepted value verbatim when possible.
    return success_object({"current_utc": current_utc if isinstance(current_utc, str) else db.clock_now().isoformat().replace("+00:00", "Z")})
