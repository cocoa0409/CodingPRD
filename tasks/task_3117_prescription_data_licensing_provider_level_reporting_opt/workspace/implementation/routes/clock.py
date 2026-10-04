"""Logical clock endpoint. PlatformAdmin only."""

from datetime import datetime, timezone

from flask import Blueprint

from db import db
from errors import err_invalid_request
from middleware import require_role
from response import success_object
from services.common import body_json, require_fields, check_str

bp = Blueprint("clock", __name__)


def _to_utc_z(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role(["PlatformAdmin"])
    data = body_json()
    require_fields(data, ["to_iso8601"])
    raw = check_str(data, "to_iso8601")
    parsed = raw
    if parsed.endswith("Z"):
        parsed = parsed[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(parsed)
    except ValueError:
        raise err_invalid_request("to_iso8601 must be a valid ISO 8601 instant")
    db.logical_clock = dt
    return success_object({"current_utc": _to_utc_z(db.logical_clock)})
