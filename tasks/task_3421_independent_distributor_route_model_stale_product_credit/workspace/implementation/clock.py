"""The logical clock (PRD 2.4). The server NEVER reads wall-clock time.

Starts fixed at CLOCK_DEFAULT_ISO; moved only via POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

from constants import CLOCK_DEFAULT_ISO

_state = {"now": None}


def _parse_dt(value):
    """Parse an ISO 8601 timestamp; naive values are treated as UTC."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset():
    _state["now"] = _parse_dt(CLOCK_DEFAULT_ISO)


def now():
    if _state["now"] is None:
        reset()
    return _state["now"]


def today():
    return now().date()


def set_current(value):
    dt = _parse_dt(value)
    if dt is None:
        return None
    _state["now"] = dt
    return dt


def iso(dt=None):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    dt = dt or now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_date(value):
    """Strict ISO date parse ('YYYY-MM-DD') -> datetime.date or None."""
    if not isinstance(value, str):
        return None
    try:
        from datetime import date as _date
        return _date.fromisoformat(value.strip())
    except ValueError:
        return None


reset()
