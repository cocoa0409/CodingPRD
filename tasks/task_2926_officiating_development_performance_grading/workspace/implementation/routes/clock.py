"""The logical clock (PRD 2.4, endpoint POST /_clock/set_current_utc)."""

from flask import Blueprint

import validation as v
from db import iso, now, set_clock
from middleware import ANY_ROLE, endpoint
from response import object_response

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(ANY_ROLE)
def set_current_utc():
    """"An administrative test-driving capability, available to all eight roles,
    sets the logical clock to a supplied UTC instant carried in a `current_utc`
    field. Setting the clock mutates no entity and runs no sweep of its own."""
    data = v.body()
    instant = v.req_datetime(data, "current_utc")
    set_clock(instant)
    return object_response({"current_utc": iso(now())})
