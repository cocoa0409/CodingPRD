"""POST /_clock/set_current_utc — test-driving logical clock (PRD 2.4)."""
from flask import Blueprint

import clock
import envelope
from auth import require_auth
from validate import body, req_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_auth(("PlatformAdmin",))
    d = body()
    dt = req_dt(d, "current_utc")
    clock.set_now(dt)
    return envelope.ok({"current_utc": clock.fmt(dt)}, 200)
