"""The logical clock capability (PRD 2.9).

The clock starts at exactly 2026-08-01T00:00:00Z and never falls back to wall
time; only this endpoint moves it, and it mutates no entity.
"""

from flask import Blueprint

from guards import as_datetime, authenticate, body
from response import ok
from store import db
from util import fmt_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(("RegionalAdmin",))
    payload = body()
    instant = as_datetime(payload, "to_iso8601")
    db.set_clock(instant)
    return ok({"current_utc": fmt_dt(instant)})
