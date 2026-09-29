"""The test-driving logical clock endpoint (PRD 2.6)."""

from flask import Blueprint

import clock
import response
import validate
from middleware import ROLE_INCENTIVE_CONTROLLER as CONTROLLER
from middleware import require_roles

bp = Blueprint("clock_endpoint", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles(CONTROLLER)
def set_current_utc():
    payload = validate.body()
    instant = validate.get_instant(payload, "to_iso8601")
    clock.set_now(instant)
    return response.object_response({"current_utc": clock.now()})
