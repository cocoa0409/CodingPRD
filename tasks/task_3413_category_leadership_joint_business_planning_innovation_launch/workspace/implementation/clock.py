"""The shared logical clock (PRD §2.4) and its PlatformAdmin-only endpoint.

The clock never reads wall-clock time. It starts at exactly
2026-09-01T00:00:00Z, is monotonic non-decreasing, and every time-windowed
rule in the system evaluates against it.
"""

from flask import Blueprint

import validation as V
from auth import ROLE_PLATFORM_ADMIN, authenticate, authorize
from constants import DEFAULT_CLOCK_START_ISO
from envelope import success
from errors import err
from timeutil import fmt_logical, parse_iso

_current = parse_iso(DEFAULT_CLOCK_START_ISO)


def now():
    return _current


bp = Blueprint("clock", __name__)


@bp.post("/jbp/_clock/set_current_utc")
def set_current_utc():
    _uid, role = authenticate()
    authorize(role, [ROLE_PLATFORM_ADMIN])
    data = V.body()
    V.check_undeclared(data, {"to_iso8601"})
    target = V.as_dt(V.require(data, "to_iso8601"), "to_iso8601")
    global _current
    if target < _current:
        err("ERR_VALIDATION", "logical clock is monotonic non-decreasing")
    _current = target
    return success({"current_utc": fmt_logical(_current)}, 200)
