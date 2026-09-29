"""Logical clock control (PRD section 2.4)."""
from flask import Blueprint

from db import db
from middleware import endpoint
from response import object_response
from validation import body, req_datetime, req_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint("DistrictAdmin")
def set_current_utc():
    data = body()
    raw = req_str(data, "current_utc")
    parsed = req_datetime(data, "current_utc")
    db.clock = parsed
    db.clock_echo = raw
    return object_response({"current_utc": raw})
