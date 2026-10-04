"""Logical clock driver (PRD 2.4). LeagueAdmin-only."""
from flask import Blueprint

import shape
from authz import LEAGUE_ADMIN, require_roles
from respond import success
from store import store
from timeutil import fmt_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(LEAGUE_ADMIN)
    b = shape.body()
    shape.no_extra(b, {"current_utc"})
    current_utc = shape.s_instant(b, "current_utc")
    store.clock = current_utc
    return success({"current_utc": fmt_dt(store.clock)})
