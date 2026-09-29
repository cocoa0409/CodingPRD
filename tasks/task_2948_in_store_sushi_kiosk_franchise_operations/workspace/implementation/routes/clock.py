"""The logical clock -- PRD 2.5. The one endpoint with no authentication."""

from flask import Blueprint

from core import LOCK, iso_instant, set_logical_now
from middleware import body, req_instant
from response import ok
from services import domain

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    payload = body()
    instant = req_instant(payload, "current_utc")
    with LOCK:
        set_logical_now(instant)
        domain.run_clock_sweeps()
    return ok({"current_utc": iso_instant(instant)})
