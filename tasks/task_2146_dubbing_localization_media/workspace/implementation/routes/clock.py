"""Test-driving logical clock."""
from flask import Blueprint

from auth import ALL_ROLES, auth
from responses import ok
from store import db, fmt_instant
from validate import body, v_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@auth("PlatformAdmin")
def set_clock():
    data = body()
    instant = v_datetime(data, "to_iso8601")
    db.clock = instant
    return ok({"current_utc": fmt_instant(db.clock)})


@bp.get("/_clock")
@auth(*ALL_ROLES)
def read_clock():
    return ok({"current_utc": fmt_instant(db.clock)})
