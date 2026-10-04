"""The test-driving logical clock endpoint, mounted OUTSIDE the /portal
prefix (PRD section 2.4)."""
from flask import Blueprint

import clock
import envelope
from auth import caller
from validate import as_str, body, req_field
from errors import invalid_request

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    caller({"PlatformAdmin"})
    data = body()
    raw = as_str(req_field(data, "current_utc"), "current_utc")
    try:
        clock.set_now(raw)
    except ValueError:
        invalid_request("current_utc is not a valid ISO 8601 timestamp")
    return envelope.obj({"current_utc": raw})
