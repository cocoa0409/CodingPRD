"""The deterministic logical clock (PRD section 2.5)."""

from flask import Blueprint

from auth import ROLES, begin
from errors import ApiError
from responses import iso_seconds, object_response
from store import store
from validators import body, req_instant

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    begin("PlatformAdmin")
    data = body()
    requested = req_instant(data, "current_utc")
    previous = store.clock
    if requested < previous:
        raise ApiError("ERR_CLOCK_REWIND", "The clock may only move forward or stand still.")
    store.clock = requested
    return object_response({"current_utc": iso_seconds(requested),
                            "previous_utc": iso_seconds(previous)})


@bp.get("/_clock")
def read_clock():
    begin(*ROLES)
    return object_response({"current_utc": iso_seconds(store.clock)})
