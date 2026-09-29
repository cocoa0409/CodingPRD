"""POST /_clock/set_current_utc (PRD 2.4)."""

from flask import Blueprint

import db as dbmod
import shapes
from db import CLOCK_EPOCH, db
from errors import ApiError
from middleware import actor
from response import object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    actor()
    data = shapes.body()
    if "current_utc" not in data or data["current_utc"] is None:
        shapes.bad("Field 'current_utc' is required.")
    raw = data["current_utc"]
    if not isinstance(raw, str):
        shapes.bad("Field 'current_utc' must be a string.")
    if not (shapes.INSTANT_RE.match(raw) or shapes.DATE_RE.match(raw)):
        raise ApiError("ERR_CLOCK_REWIND_FORBIDDEN",
                       "The supplied clock value is not a valid ISO-8601 UTC instant.")
    try:
        moment = shapes.parse_instant_string(raw, "current_utc")
    except ApiError:
        raise ApiError("ERR_CLOCK_REWIND_FORBIDDEN",
                       "The supplied clock value is not a valid ISO-8601 UTC instant.")
    if moment < CLOCK_EPOCH:
        raise ApiError("ERR_CLOCK_REWIND_FORBIDDEN",
                       "The logical clock may not be moved earlier than %s."
                       % dbmod.fmt_instant(CLOCK_EPOCH))
    db.clock = moment
    return object_response({})
