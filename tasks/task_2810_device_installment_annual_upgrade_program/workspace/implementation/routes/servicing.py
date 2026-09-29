"""Servicing sweep and the test-driving logical clock (PRD 3.6, 2.4)."""
from flask import Blueprint

import clock
import response
import validate
from constants import ROLE_COLLECTIONS_OFFICER, ROLE_PROGRAM_ADMIN
from errors import ApiError
from middleware import require_roles
from services import servicing as servicing_service

bp = Blueprint("servicing", __name__)


@bp.post("/servicing/daily-run")
def daily_run():
    require_roles(ROLE_COLLECTIONS_OFFICER, ROLE_PROGRAM_ADMIN)
    validate.body()
    summary = servicing_service.run_daily_sweep(clock.now())
    return response.object_response(summary)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(ROLE_PROGRAM_ADMIN)
    payload = validate.body()
    raw = validate.req_str(payload, "to_iso8601")
    moment = clock.parse_iso8601(raw)
    if moment is None:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC",
                       "to_iso8601 is not a parseable ISO 8601 UTC instant.")
    if moment < clock.now():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC",
                       "The logical clock only ever moves forward.")
    clock.set_now(moment)
    return response.object_response({"current_utc": clock.now_iso()})
