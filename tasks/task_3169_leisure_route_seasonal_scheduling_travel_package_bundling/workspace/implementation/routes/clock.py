"""Logical clock endpoint."""

import db
from flask import Blueprint

from common import body, require_field, parse_datetime
from errors import ApiError
from middleware import require_any_authenticated
from response import ok

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_any_authenticated()
    data = body()
    current_utc = require_field(data, "current_utc", str)
    try:
        parse_datetime(current_utc)
    except (ValueError, TypeError):
        raise ApiError(
            "ERR_VALIDATION", "current_utc must be a valid ISO8601 timestamp", 422
        )
    db.current_utc = current_utc
    return ok({"current_utc": db.current_utc})
