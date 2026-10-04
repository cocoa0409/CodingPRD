"""Logical clock control (platform surface, OUTSIDE the /registry prefix).

POST /_clock/set_current_utc — PlatformAdmin only. The clock moves forward
only; advancing it atomically runs the ops checkpoint (facility expiry sweep,
then detention deadline sweep with the 24h grace).
"""
from flask import Blueprint

import db
import services
from auth import require_roles
from envelope import ok, json_body
from errors import ApiError

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc(caller_id, caller_role):
    body = json_body()
    target = db.parse_dt(body.get("current_utc"))
    if target is None or target <= db.now():
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "current_utc must be a valid ISO-8601 instant later than the current logical time",
        )
    db.set_clock(target)
    expired_ids, auto_refused_ids = services.run_checkpoint(target)
    return ok(
        {
            "current_utc": db.fmt_dt(target),
            "expired_facility_ids": expired_ids,
            "auto_refused_entry_ids": auto_refused_ids,
        }
    )
