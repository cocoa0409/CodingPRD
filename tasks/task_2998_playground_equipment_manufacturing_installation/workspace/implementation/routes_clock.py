"""The logical plant clock (PRD section 2.5).  Mutates no business rows."""

from flask import Blueprint

import validate as v
from auth import ALL_ROLES, authenticate
from envelope import object_response
from errors import ApiError
from store import parse_date, store

bp = Blueprint("clock", __name__)


@bp.route("/playground/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate(ALL_ROLES)
    body = v.raw_body()
    v.string(body, "current_utc", min_len=1)
    instant = v.instant_field(body, "current_utc")

    # Time moves forward freely but may not be rewound past written history.
    requested_date = instant.date()
    for project in store.all("project"):
        recorded = project.get("installed_on")
        if recorded and requested_date < parse_date(recorded):
            raise ApiError("ERR_CLOCK_REWIND_FORBIDDEN")

    store.clock.set(instant, body["current_utc"])
    return object_response({"current_utc": store.clock.raw})
