"""The underscore namespace that makes time drivable -- PRD 2.6 / 4."""

from flask import Blueprint

from db import db
from middleware import LMS_ADMIN, as_dt, body
from routes.common import guard, plain_ok
from util import fmt_dt

bp = Blueprint("testing", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    """Moves the server-held logical clock; mutates no entity (PRD 2.6)."""
    guard(LMS_ADMIN)
    payload = body()
    moment = as_dt(payload, "to_iso8601", required=True)
    db.clock = moment
    return plain_ok({"to_iso8601": fmt_dt(moment),
                     "current_utc": fmt_dt(moment)})
