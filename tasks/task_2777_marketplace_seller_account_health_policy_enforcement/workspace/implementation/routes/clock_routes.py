"""POST /_clock/set_current_utc — the logical clock (PRD 2.4)."""

from flask import Blueprint

import clock
import constants as C
import middleware as mw
import response
import validators as v

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
@mw.require(C.ROLE_OFFICER)
def set_current_utc():
    data = v.body()
    instant = v.req_datetime(data, "to_iso8601")
    clock.set_now(instant)
    return response.empty(200)
