"""The server-owned logical clock (PRD 2.4)."""
from flask import Blueprint

import auth
import clock
import response
import validate

bp = Blueprint("clock_routes", __name__)


@bp.post("/store-ops/_clock/set_current_utc")
def set_current_utc():
    auth.authenticate(auth.ALL_ROLES)
    body = validate.body()
    moment = validate.instant(body, "current_utc")
    clock.set_now(moment)
    return response.ok({"current_utc": clock.iso(clock.now())})
