"""Logical clock with fixed startup default."""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = [DEFAULT_CLOCK]


def now():
    return _current[0]


def set_clock(dt):
    _current[0] = dt


def fmt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-09-01T00:00:00.000Z"""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.astimezone(timezone.utc).microsecond // 1000:03d}Z"


def parse(s):
    """Parse an ISO-8601 timestamp into an aware UTC datetime."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


SENTINEL_END = datetime(9999, 12, 31, 0, 0, 0, tzinfo=timezone.utc)
