"""Platform logical clock endpoint (UNPREFIXED — PRD section 2.5).

POST /_clock/set_current_utc lives outside the /potato-ops prefix, verbatim.
"""

import db
import domain
from errors import ApiError
from flask import Blueprint
from middleware import require_roles
from response import success_object
from util import body_json, parse_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_current_utc():
    body = body_json()
    current_utc = body.get("current_utc")
    dt = parse_dt(current_utc)
    if dt is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'current_utc': is required and must be an ISO 8601 datetime",
            400,
        )
    db.set_clock(dt)
    domain.clock_sweep(dt)
    return success_object({}, 200)
