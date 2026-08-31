"""Logical-clock test-driving surface."""
from flask import Blueprint

import envelope
import store
import validate as V
from auth import endpoint

bp = Blueprint("clock", __name__)


@bp.post("/vm/_clock/set_current_utc")
@endpoint(["PlatformAdmin"])
def set_clock():
    data = V.body()
    moment = V.as_datetime(data, "to_iso8601")
    store.set_now(moment)
    return envelope.ok({"current_utc": store.now_iso()})
