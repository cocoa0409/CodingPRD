"""POST /_clock/set_current_utc — lives OUTSIDE the api_prefix (PRD §2.5)."""
from flask import Blueprint

from db import store
from errors import err
from middleware import auth, require_role
from services.engine import missed_sweep
from util import fmt_dt, get_body, ok_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = auth()
    data = get_body()
    raw = data.get("to_iso8601")
    if not isinstance(raw, str) or not raw:
        err("ERR_VALIDATION", "to_iso8601 is required and must be an ISO 8601 datetime")
    try:
        from util import parse_dt
        new_clock = parse_dt(raw)
    except (ValueError, TypeError):
        err("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 datetime")
    require_role(role, ["PlatformAdmin"])
    store.clock = new_clock
    bumped = set()
    missed_sweep(new_clock, bumped)
    return ok_object({"current_utc": fmt_dt(store.clock)}, 200)
