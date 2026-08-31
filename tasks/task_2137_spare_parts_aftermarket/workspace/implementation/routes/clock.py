"""The logical clock control (PRD section 2.4)."""
from flask import Blueprint

import auth
import envelope
import store
from errors import ApiError

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.require("PlatformAdmin")
    data = auth.body()
    target = auth.req_datetime(data, "to_iso8601")
    if target < store.now():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    store.set_clock(target)
    return envelope.ok({"current_utc": store.iso(store.now())})
