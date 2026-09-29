"""POST /_clock/set_current_utc (PRD section 2.4)."""
from flask import Blueprint

import clock
import response
from errors import ApiError
from middleware import body, endpoint
from services.validate import req_ts

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint("TerminalAdmin")
def set_current_utc():
    target = req_ts(body(), "to_iso8601")
    if target < clock.now():
        raise ApiError("ERR_INVALID_REQUEST", "The logical clock is monotonic and may not move backwards.")
    clock.set_now(target)
    return response.single({"current_utc": clock.now_iso()})
