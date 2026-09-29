"""Logical clock. PRD 2.4: nothing in this system reads the wall clock."""
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_CLOCK}


def reset():
    _state["now"] = DEFAULT_CLOCK


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt
    return _state["now"]


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def plus_days(dt, days):
    return dt + timedelta(days=days)


def floor_days_between(earlier, later):
    """floor((later - earlier) / 86400 seconds)."""
    seconds = (later - earlier).total_seconds()
    return int(seconds // 86400)
