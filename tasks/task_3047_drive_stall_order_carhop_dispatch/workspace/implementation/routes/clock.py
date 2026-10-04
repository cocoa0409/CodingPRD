"""Logical-clock test-driving endpoint (PRD 2.6)."""
from datetime import datetime, timezone

import db as db_module
from errors import invalid_request
from middleware import require_auth, body_json
from response import success_object
from serializers import _fmt
from . import clock_bp


@clock_bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_auth(["PlatformAdmin"])
    body = body_json()
    raw = body.get("current_utc")
    if not isinstance(raw, str):
        invalid_request("current_utc must be an ISO 8601 timestamp string")
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        invalid_request("current_utc must be an ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    db_module.set_clock(dt.astimezone(timezone.utc))
    return success_object({"current_utc": _fmt(db_module.now())})
