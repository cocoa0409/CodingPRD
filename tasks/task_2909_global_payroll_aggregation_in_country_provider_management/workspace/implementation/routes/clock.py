"""The administrative logical-clock endpoint, outside the /payroll prefix."""
from flask import Blueprint

import validate as v
from auth import require
from common import CLOCK_ROLES, set_clock
from response import empty_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require(*CLOCK_ROLES)
def set_current_utc():
    body = v.json_body()
    moment = v.req_instant(body, "to_iso8601")
    set_clock(moment)
    return empty_response()
