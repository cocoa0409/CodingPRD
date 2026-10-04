"""POST /_clock/set_current_utc — the logical clock test-driving capability."""
from flask import Blueprint, request

from core import base, config as C
from core.errors import bad_request
from core.middleware import route
from core.response import object_response

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@route("/_clock/set_current_utc", "POST")
def set_current_utc():
    body = base.get_body(request.get_json(silent=True))
    raw = body.get("to_iso8601")
    if raw is None:
        raise bad_request("to_iso8601 is required")
    dt = C.parse_dt(raw)
    if dt is None:
        raise bad_request("to_iso8601 must be a valid ISO 8601 instant")
    C.set_clock(C.iso(dt))
    return object_response({})