"""Platform logical-clock endpoint (mounted OUTSIDE the /identity-protection
prefix). Setting the clock runs exactly two sweeps: expired dependent-conflict
evidence windows auto-resolve, and elapsed BOOKED appointments complete.
Verification cases are deliberately not swept."""
from flask import Blueprint

from auth import require_roles
from domain import run_clock_sweeps
from envelope import ok
from store import DB
from validate import body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles(["SystemAdmin"])
    to = req_datetime(body(), "to_iso8601")
    DB.set_clock(to)
    run_clock_sweeps()
    return ok({"current_utc": DB.now_iso()})
