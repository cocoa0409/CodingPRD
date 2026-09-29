"""The logical settlement clock control endpoint (PRD section 2.5)."""
from flask import Blueprint, request

import clock
import middleware
import response
import validators

bp = Blueprint("clock_routes", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    middleware.authenticate()
    body = validators.body_of(request)
    validators.require(body, ["current_utc"])
    clock.set_now(validators.ts_value(body, "current_utc", required=True))
    return response.object_response({})
