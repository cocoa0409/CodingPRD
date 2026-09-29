"""The logical clock capability (PRD 2.5).

Exempt from the header authentication and the role check of 2.1.
"""
from flask import Blueprint

from envelope import respond_object
from errors import bad_request
from util import clock
from validators import get_body, req_string

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    body = get_body()
    raw = req_string(body, "to_iso8601")
    try:
        current_utc = clock.set_from_iso(raw)
    except Exception:
        raise bad_request("Field 'to_iso8601' is not a valid ISO 8601 instant")
    return respond_object({"current_utc": current_utc})
