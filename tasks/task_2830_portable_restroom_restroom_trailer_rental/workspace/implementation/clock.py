"""Server-owned logical clock (PRD 2.4).

The clock never reads wall-clock time. Before it is repositioned it reads
exactly 2026-08-01T00:00:00Z.
"""
from datetime import datetime, timedelta, timezone

DEFAULT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_INSTANT}


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now():
    return _state["now"]


def now_iso():
    return iso(_state["now"])


def today():
    """Calendar date (YYYY-MM-DD) of the logical clock instant."""
    return _state["now"].astimezone(timezone.utc).strftime("%Y-%m-%d")


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)


def parse_instant(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    text = raw
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def plus_days(dt, days):
    return dt + timedelta(days=days)
