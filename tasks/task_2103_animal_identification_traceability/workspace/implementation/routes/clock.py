"""Administrative logical-clock driver (PRD 2.4)."""
from flask import Blueprint

import shape
from authz import PROGRAM_ADMIN, require_roles
from db import store
from respond import success
from timeutil import fmt_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(PROGRAM_ADMIN)
    body = shape.body()
    to_iso8601 = shape.s_instant(body, "to_iso8601")
    store.clock = to_iso8601
    return success({"current_utc": fmt_dt(store.clock)})
