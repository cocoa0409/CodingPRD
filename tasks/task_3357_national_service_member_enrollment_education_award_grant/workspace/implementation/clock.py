"""Logical UTC clock (PRD 2.4).

Starts at exactly 2026-09-01T00:00:00Z, never falls back to wall-clock time,
and moves only via POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

_INITIAL = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _INITIAL


def now():
    return _current


def set_current(dt):
    global _current
    _current = dt


def iso(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(_current)


def parse_datetime(value):
    """Parse an ISO 8601 timestamp (Z or offset). Returns None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
