"""The logical-clock control operation (PRD 2.4)."""

from flask import Blueprint

from db import db
from errors import bad_request
from middleware import authenticate, body, require_str
from response import ok_empty
from timeutil import parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@bp.post("/research/_clock/set_current_utc")
def set_current_utc():
    authenticate(["PlatformAdmin"], anonymous=True)
    data = body()
    value = require_str(data, "current_utc")
    instant = parse_dt(value)
    if instant is None:
        raise bad_request("current_utc must be an ISO 8601 UTC instant.")
    db.set_clock(instant)
    return ok_empty(200)
