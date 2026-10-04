"""Logical clock (PRD 2.5) and timestamp helpers.

All domain temporal reasoning uses the logical clock; it starts at exactly
2026-09-01T00:00:00Z on every boot and never falls back to wall-clock time.
created_at / updated_at metadata stamps use the wall clock (PRD 2.4 only
requires an ISO8601 UTC timestamp for those).
"""
from datetime import datetime, timedelta, timezone

from constants import CLOCK_START_ISO

UTC = timezone.utc


def iso3(dt):
    """ISO 8601 UTC string with exactly three fractional digits."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 datetime; returns an aware UTC datetime or None."""
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_date(value):
    """Parse a strict YYYY-MM-DD date; returns the string normalized or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None
    if d.strftime("%Y-%m-%d") != s:
        return None
    return s


def wall_now():
    return datetime.now(UTC)


def wall_now_iso():
    return iso3(wall_now())


# --- The logical clock --------------------------------------------------------
_state = {"now": parse_dt(CLOCK_START_ISO)}


def now():
    return _state["now"]


def now_iso():
    return iso3(_state["now"])


def set_now(dt):
    _state["now"] = dt


def days(n):
    return timedelta(days=n)


def hours(n):
    return timedelta(hours=n)
