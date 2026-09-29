"""The logical clock endpoint (PRD section 2.6)."""
from flask import Blueprint

import clock
import middleware
import response
import validate

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@middleware.roles(*middleware.ALL_ROLES)
def set_current_utc():
    data = validate.body()
    value = validate.req_instant(data, "current_utc")
    clock.set_now(value)
    return response.empty(200)
