"""The logical clock.

Startup default is exactly 2026-09-01T00:00:00Z; the clock never falls back
to wall-clock time. Every server-stamped timestamp reads from this clock.
"""
from datetime import datetime, timedelta, timezone

_DEFAULT_RAW = "2026-09-01T00:00:00Z"
_now = None
_raw = None


def _parse(text):
    if not isinstance(text, str):
        raise ValueError("not a string")
    s = text.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _init():
    global _now, _raw
    _now = _parse(_DEFAULT_RAW)
    _raw = _DEFAULT_RAW


_init()


def now():
    return _now


def raw_now():
    return _raw


def set_now(raw):
    """Advance the logical clock; returns the parsed instant. Raises
    ValueError if the input is not a parseable ISO 8601 instant."""
    global _now, _raw
    dt = _parse(raw)
    _now = dt
    _raw = raw
    return dt


def parse_instant(text):
    return _parse(text)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def today_str():
    return _now.date().isoformat()


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
