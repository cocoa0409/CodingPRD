"""Logical clock endpoint."""
from flask import Blueprint

import middleware as mw
from db import db
from response import success_object

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    b = mw.body()
    dt = mw.req_datetime(b, "to_iso8601")
    db.clock = dt
    db.clock_set = True
    return success_object({"current_utc": mw.fmt_clock(db.clock)})
