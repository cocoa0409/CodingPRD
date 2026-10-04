"""The program's logical clock.

The clock never reads wall-clock time: it starts at 2026-09-01T00:00:00Z on
every boot and is moved only through POST /ap-program/_clock/set_current_utc.
Entity timestamps are stamped from this clock.
"""

from datetime import datetime, timedelta, timezone

from constants import DEFAULT_CLOCK_UTC
from errors import fail

_STATE = {"current": None}


def _parse(iso):
    if not isinstance(iso, str) or not iso.strip():
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be a non-empty ISO 8601 instant.")
    text = iso.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "to_iso8601 is not a parseable ISO 8601 instant.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset():
    _STATE["current"] = _parse(DEFAULT_CLOCK_UTC)


def now():
    """Current logical instant as an aware UTC datetime."""
    if _STATE["current"] is None:
        reset()
    return _STATE["current"]


def set_current(iso):
    _STATE["current"] = _parse(iso)
    return _STATE["current"]


def iso(dt):
    """ISO 8601 UTC with three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(now())


def parse_instant(value):
    """Parse an arbitrary payload instant; returns an aware datetime."""
    return _parse(value)


def instant_or_none(value):
    if value is None:
        return None
    return _parse(value)


def shift_days(dt, days):
    return dt + timedelta(days=days)


def later(a, b):
    return a if a >= b else b
