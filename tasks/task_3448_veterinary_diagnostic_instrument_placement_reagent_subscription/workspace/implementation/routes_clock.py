"""POST /api/_clock/set_current_utc — test-driving logical clock."""
from flask import Blueprint

import db
import services
import util
from errors import err

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    _, role = util.auth()
    util.require(role, ["PlatformAdmin"])
    b = util.body()
    try:
        target = util.parse_iso(b.get("to_iso8601"))
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST",
                  "to_iso8601 must be a valid ISO 8601 timestamp")
    if target <= db.now():
        raise err("ERR_INVALID_REQUEST",
                  "to_iso8601 must be strictly later than the current logical time")
    db.set_now(target)
    services.sweep(target)
    return util.ok({"current_utc": util.iso_z(target)})
