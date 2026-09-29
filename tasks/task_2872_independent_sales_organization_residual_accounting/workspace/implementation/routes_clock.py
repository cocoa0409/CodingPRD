"""The logical clock (PRD 2.6)."""
from flask import Blueprint

from apierrors import fail
from auth import authorize
from envelope import object_response
from shapes import as_str, body
from store import db, parse_instant

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorize("IsoAdmin")
    payload = body()
    raw = as_str(payload, "current_utc")
    parsed = parse_instant(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 UTC instant")
    db.set_clock(raw, parsed)
    return object_response({"current_utc": db.clock_raw})
