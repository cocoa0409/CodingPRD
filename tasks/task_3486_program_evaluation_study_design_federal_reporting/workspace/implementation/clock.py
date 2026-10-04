"""Server-maintained logical clock.

The clock never falls back to wall-clock time. Before any
POST /_clock/set_current_utc call it reads exactly CLOCK_DEFAULT_UTC.
Every temporal rule (IRB approval windows, wave windows, report
deadlines) is evaluated against this clock.
"""
from datetime import datetime, timezone

CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"

_current_dt = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def parse_iso(value):
    """Parse an ISO-8601 string into an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1:] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_dt():
    return _current_dt


def set_now(dt):
    global _current_dt
    _current_dt = dt


def fmt_dt(dt):
    """Second-precision UTC ISO-8601 with Z suffix (business datetime fields)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_dt3(dt):
    """Millisecond-precision (three fractional digits) UTC ISO-8601."""
    base = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return "%s.%03dZ" % (base, dt.microsecond // 1000)


def now_iso():
    return fmt_dt(_current_dt)


def now_iso3():
    return fmt_dt3(_current_dt)
