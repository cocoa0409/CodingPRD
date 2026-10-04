"""POST /api/_clock/set_current_utc — advance the logical clock + run sweep."""
from flask import Blueprint

from auth import require_roles
from envelope import success_obj
from errors import fail
from store import iso3, set_clock
from sweep import run_sweep
from validate import body_dict
from dates import parse_iso

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    require_roles("PlatformAdmin")
    body = body_dict()
    dt = parse_iso(body.get("to_iso8601"))
    if dt is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    set_clock(dt)
    run_sweep()
    return success_obj({"current_utc": iso3(dt)})
