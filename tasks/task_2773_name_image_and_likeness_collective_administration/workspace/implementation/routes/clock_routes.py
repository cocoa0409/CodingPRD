"""POST /nil/_clock/set_current_utc — the only way to move the logical clock."""

from flask import Blueprint

import auth
import clock
import envelope
import shape

bp = Blueprint("clock_routes", __name__)


@bp.route("/nil/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth.authenticate([auth.PLATFORM_ADMIN])
    body = shape.body()
    target = shape.ts_field(body, "current_utc", required=True)
    previous = clock.set_now(target)
    return envelope.object_response({
        "current_utc": clock.format_ts(target),
        "previous_utc": clock.format_ts(previous),
    })
