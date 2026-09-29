"""The server side logical clock (PRD 2.4).

Every temporal rule in the system reads this clock; it never falls back to the
real time of day.  A freshly booted process reads 2026-08-01T00:00:00Z.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

_state = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _state["now"]


def set_now(value):
    _state["now"] = value
    return value


def real_now():
    return datetime.now(timezone.utc)


def fmt(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
        value.microsecond // 1000,
    )
