"""The test-driving logical clock endpoint."""

from flask import Blueprint

import auth
import clock
import parsers as P
from errors import ERR_INVALID_STATE, ApiError
from response import object_response
from routes.common import guard
from services.changes import apply_time_triggered_transitions

bp = Blueprint("clock", __name__)

STAFF = (auth.EDITORIAL_STAFF,)


@bp.post("/_clock/set_current_utc")
@guard(STAFF)
def set_current_utc(actor):
    data = P.body()
    target = P.dt(data.get("to_iso8601"))
    if target is None:
        raise ApiError(ERR_INVALID_STATE, "to_iso8601 is required")

    clock.set_logical_now(target)
    # Setting the clock forward applies every time-triggered transition whose
    # precondition the new instant satisfies (PRD.md 2.8), including the
    # comment-window closure that moves a change out of POSTED_FOR_COMMENT.
    apply_time_triggered_transitions()
    return object_response({}, 200)