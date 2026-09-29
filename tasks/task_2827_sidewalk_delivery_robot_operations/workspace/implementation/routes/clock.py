"""Logical clock endpoint. Touches no row and bumps no version."""

from flask import Blueprint

from db import db, now_iso, parse_ts
from middleware import ALL_ROLES, authorize, body, check_timestamp
from response import object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(ALL_ROLES)
    payload = body()
    value = check_timestamp(payload, "current_utc")
    db.clock = parse_ts(value)
    return object_response({"current_utc": now_iso()})
