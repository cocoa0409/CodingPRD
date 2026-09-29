"""The logical clock (PRD 2.4, 3.9).  It only ever moves forward."""

from flask import Blueprint

from auth import require_roles
from errors import ApiError
from response import ok
from store import store
from validation import body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("AgencyController")
def set_clock():
    data = body()
    current_utc = data.timestamp("current_utc")
    if current_utc < store.now():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    store.set_clock(current_utc)
    return ok({})
