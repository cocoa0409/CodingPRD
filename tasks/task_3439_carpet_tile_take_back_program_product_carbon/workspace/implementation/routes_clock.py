"""Logical clock administration (PRD 2.5). Lives OUTSIDE the /carpetloop
prefix. The clock starts at exactly 2026-09-01T00:00:00Z, is set only through
this endpoint, and the server never falls back to wall-clock time."""
from flask import Blueprint

from auth import authenticate, authorize
from envelope import success
from errors import ApiError
from store import STORE
from util import get_body, parse_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    raw = body.get("current_utc")
    dt = parse_dt(raw)
    if dt is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Field 'current_utc': required ISO-8601 timestamp"
        )
    STORE.clock = dt
    # The endpoint echoes the supplied value as current_utc (PRD 2.5).
    return success({"current_utc": raw}, 200)
