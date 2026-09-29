"""The server-side logical clock (PRD 2.4)."""

from flask import Blueprint

from response import object_response
from store import fmt_ts, set_clock
from validation import ALL_ROLES, Body, authenticate_and_authorize, json_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate_and_authorize(ALL_ROLES)
    body = Body(json_body())
    instant = body.req_ts("current_utc")
    set_clock(instant)
    return object_response({"current_utc": fmt_ts(instant)})
