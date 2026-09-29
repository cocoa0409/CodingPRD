"""The logical clock (PRD 2.4).

The clock's startup default is exactly 2026-08-01T00:00:00Z; before any call to
this endpoint the server reads that default and never falls back to wall-clock
time.  Setting the clock mutates no entity.
"""

from flask import Blueprint

from auth import BUREAU_ADMIN, endpoint
from response import object_response
from store import db
from util import format_instant
from validation import body_json, req_instant

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(BUREAU_ADMIN)
def set_current_utc():
    body = body_json()
    instant = req_instant(body, "to_iso8601")
    db.clock = instant
    return object_response({"current_utc": format_instant(instant)})
