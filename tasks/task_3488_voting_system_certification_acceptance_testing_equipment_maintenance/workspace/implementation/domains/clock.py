"""Platform logical clock endpoint (PRD 2.4).

UNPREFIXED: mounts at the server root, NOT under /evote. Moving the clock
does not itself transition certificates; expiry applies lazily on reads.
"""
from flask import Blueprint

from auth import auth_context, require_role
from envelope import ok_object
from errors import err_invalid_request
from store import db
from util import fmt_dt, parse_iso
from validation import body_json, no_extra

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = auth_context()
    require_role(role, {"PlatformAdmin"})
    body = body_json()
    no_extra(body, {"to_iso8601"})
    dt = parse_iso(body.get("to_iso8601"))
    if dt is None:
        err_invalid_request("to_iso8601 must be an ISO 8601 UTC instant")
    db.clock = dt
    return ok_object({"current_utc": fmt_dt(db.clock)}, 200)
