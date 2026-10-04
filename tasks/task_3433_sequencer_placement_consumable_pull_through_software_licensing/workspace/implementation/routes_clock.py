"""POST /genomics/_clock/set_current_utc — the test-driving logical clock."""

from flask import Blueprint

from auth import require_roles
from cascades import run_clock_sweeps
from envelope import ok
from errors import ApiError
from store import now, set_clock
from timeutil import iso
from validate import f_dt, get_body

bp = Blueprint("clock", __name__)


@bp.post("/genomics/_clock/set_current_utc")
def set_current_utc():
    require_roles("PlatformAdmin")
    body = get_body()
    target = f_dt(body, "to_iso8601")
    current = now()
    if not (target > current):
        raise ApiError(
            "ERR_CLOCK_REGRESSION",
            422,
            "to_iso8601 must be strictly greater than the current logical clock",
        )
    set_clock(target)
    lots_expired, contracts_expired, transitions_expired = run_clock_sweeps()
    return ok(
        {
            "current_utc": iso(target),
            "lots_expired": lots_expired,
            "contracts_expired": contracts_expired,
            "transitions_expired": transitions_expired,
        }
    )
