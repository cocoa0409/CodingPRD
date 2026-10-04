"""Test-driving surface: the server-side logical clock (PRD 2.6).

Before this endpoint is ever called the logical clock reads exactly
2026-09-01T00:00:00Z; it never falls back to wall-clock time.
"""

from flask import Blueprint

import db
from middleware import STORE_ADMIN, authenticate, get_body, parse_timestamp
from response import object_response
from response import iso_timestamp

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate([STORE_ADMIN])
    body = get_body()
    db.set_clock(parse_timestamp(body, "to_iso8601"))
    # Lazy auto-close of stale ACTIVE programs is evaluated on next access.
    return object_response({"current_utc": iso_timestamp(db.clock_now())})
