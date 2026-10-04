"""POST /_clock/set_current_utc — the only platform endpoint (unprefixed).

A BoardAdmin moves the logical clock by supplying to_iso8601; arbitrary
values are accepted and monotonicity is not enforced. The response reports
the new current_utc. Lazy clock-driven states resolve on subsequent
reads/writes of the affected resources.
"""

from flask import Blueprint

import clock
from auth import get_context, require_roles
from envelope import ok_object
from validate import get_body, req_str

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _user_id, role = get_context()
    require_roles(role, ("BoardAdmin",))
    body = get_body()
    value = req_str(body, "to_iso8601")
    clock.set_clock(value)
    return ok_object({"current_utc": clock.get_clock()}, status=200)
