"""Routes: logical clock test-driving endpoint."""

from flask import Blueprint

from db import db, iso3
from helpers import auth, require_role, body, idem_begin, dt_field
from response import success_obj

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    role, _ = auth()
    ctx = idem_begin()
    require_role(role, ["DIVISION_PRESIDENT"])
    b = body()
    to = dt_field(b, "to_iso8601")
    db.clock = to
    return success_obj({"current_utc": iso3(db.clock)})
