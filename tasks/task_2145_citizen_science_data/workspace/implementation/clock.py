"""Logical clock.  The server never reads real wall-clock time."""
from datetime import datetime, timezone, timedelta

INITIAL = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": INITIAL}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt
    return _state["now"]


def reset():
    _state["now"] = INITIAL


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt(now())


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def plus_days(dt, days):
    return dt + timedelta(days=days)
