"""Logical clock: starts at 2026-09-01T00:00:00Z, advances only via API."""

from datetime import datetime, timezone

_start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _start


def now():
    return _current


def set_now(dt):
    global _current
    _current = dt


def iso(dt):
    """Format a datetime as ISO8601 UTC with three fractional digits, Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO8601 timestamp string; returns aware datetime or raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
