"""Platform logical-clock endpoint (PRD §2.5).

Mounted OUTSIDE the /wetland-permits api_prefix, exactly as declared:
POST /_clock/set_current_utc (SystemAdmin only).
"""

from flask import Blueprint

from cascades import clock_transitions
from db import get_clock, iso, set_clock
from errors import api_err
from helpers import get_body, req_datetime
from middleware import require_roles
from response import success_obj

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles(["SystemAdmin"])
    body = get_body()
    target = req_datetime(body, "to_iso8601")
    # Priority 31: the logical clock is strictly monotonic.
    if not target > get_clock():
        raise api_err("ERR_CLOCK_REGRESSION",
                      "to_iso8601 must be strictly greater than the current "
                      "logical clock value")
    set_clock(target)
    clock_transitions(target)
    return success_obj({"current_utc": iso(target)})
