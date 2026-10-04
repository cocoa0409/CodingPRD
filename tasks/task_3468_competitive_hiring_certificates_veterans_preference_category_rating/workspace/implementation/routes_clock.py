"""PlatformAdmin logical-clock endpoint (PRD 2.5). Lives OUTSIDE the
/hiring api_prefix. The clock never falls back to wall-clock time."""
from flask import Blueprint

from auth import get_auth, require_roles
from envelope import success_empty
from errors import invalid_request
from store import parse_dt, set_clock
from validate import get_body

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    body = get_body()
    dt = parse_dt(body.get("to_iso8601"))
    if dt is None:
        invalid_request("to_iso8601 must be an ISO 8601 datetime")
    set_clock(dt)
    return success_empty(200)
