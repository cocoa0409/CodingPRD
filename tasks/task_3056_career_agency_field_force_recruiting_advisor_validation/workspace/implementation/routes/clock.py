"""Logical clock (scaffold §1.5; PRD §2.5)."""

from flask import Blueprint

from db import db
from errors import err, ERR_INVALID_REQUEST
from middleware import body, required
from response import ok
from routes._shared import authed

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@authed(["PlatformAdmin"])
def set_clock(user_id, role):
    data = body()
    current_utc = required(data, "current_utc")
    if not isinstance(current_utc, str):
        raise err(ERR_INVALID_REQUEST, "current_utc must be an ISO 8601 string")
    from db import parse_dt
    value = parse_dt(current_utc)
    db.set_clock(value)
    return ok({}, 200)