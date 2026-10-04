# Logical clock test-driving endpoint (PRD 2.4).
from flask import Blueprint, request

import authz
import clock
import envelope
import errors
import validate

bp = Blueprint("clockroute", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    role, _uid = authz.authenticate()
    authz.require_roles(role, ("ManufacturerAdmin",))
    body = validate.body_json(request)
    to_iso8601 = validate.req_str(body, "to_iso8601")
    try:
        clock.CLOCK.set(to_iso8601)
    except (ValueError, TypeError):
        errors.validation("to_iso8601 must be an ISO 8601 UTC timestamp")
    return envelope.success_object({"current_utc": clock.CLOCK.current_utc_echo()})
