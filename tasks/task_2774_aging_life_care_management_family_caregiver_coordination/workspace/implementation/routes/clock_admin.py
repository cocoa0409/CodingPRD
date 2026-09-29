"""The single administrative surface that drives the logical clock."""
from flask import Blueprint

import auth
import clock
import envelope
import validators as v

bp = Blueprint("clock_admin", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth.actor_for(auth.ROLE_ADMIN)
    body = v.json_body()
    moment = v.req_dt(body, "to_iso8601")
    clock.set_now(moment)
    return envelope.ok({"current_utc": clock.iso(clock.now())})
