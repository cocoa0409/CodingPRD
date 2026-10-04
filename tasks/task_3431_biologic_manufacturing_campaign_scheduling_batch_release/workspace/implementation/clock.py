"""Deterministic logical clock (PRD 2.4).

Defaults to exactly 2026-09-01T00:00:00Z before any client call sets it and
never falls back to wall-clock time. All temporal rules read now(); all entity
timestamps (created_at, updated_at, *_at event stamps) are taken from it.
Datetime comparisons are made at second precision (PRD 2.7), so parsing
truncates any fractional part.
"""
from datetime import datetime, timedelta, timezone

from constants import DEFAULT_CLOCK_STR

_now = None  # datetime, timezone-aware UTC


def _default():
    return datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    global _now
    if _now is None:
        _now = _default()
    return _now


def set_now(dt):
    global _now
    _now = dt


def parse_dt(value):
    """Parse an ISO 8601 UTC datetime string; None if malformed.

    Accepts a trailing 'Z' or a numeric offset, with or without fractional
    seconds. Fractional seconds are truncated (second-precision comparisons).
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def hours_between(earlier, later):
    """Whole/fractional hours from earlier to later (timedelta hours)."""
    return (later - earlier).total_seconds() / 3600.0
