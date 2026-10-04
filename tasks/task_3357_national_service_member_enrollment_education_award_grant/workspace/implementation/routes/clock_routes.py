from flask import Blueprint

import auth
import clock
import util
from errors import ApiError

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer"])
    body = util.body_json()
    dt = clock.parse_datetime(body.get("to_iso8601"))
    if dt is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "to_iso8601 must be a valid ISO8601 timestamp"
        )
    clock.set_current(dt)
    return util.ok({"current_utc": clock.iso(dt)}, 200)
