"""The logical clock (PRD §2.4).

Repositioning the clock touches no stored row, advances no version and
recomputes nothing.
"""

from flask import Blueprint

from db import iso, now, set_clock
from middleware import CLOCK_ROLES, roles
from response import object_response
from services.validate import Body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@roles(*CLOCK_ROLES)
def set_current_utc():
    body = Body(require_body=True)
    instant, _raw = body.instant_field("to_iso8601", required=True)
    set_clock(instant)
    return object_response({"current_utc": iso(now())})
