"""The single logical clock (PRD section 2.5). Never the wall clock.

All system-stamped datetimes are normalized to UTC and rendered with exactly
three fractional digits and a Z suffix, so stored timestamp strings compare
lexicographically in chronological order.
"""
from datetime import date, datetime, timezone

import constants as C

_current = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)  # CLOCK_START_ISO


def now():
    return _current


def today():
    return _current.date()


def set_current(dt):
    global _current
    _current = dt


def fmt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt(_current)


def parse_dt(s):
    """Parse an ISO 8601 datetime; accepts a trailing Z or an explicit offset.
    Naive inputs are interpreted as UTC. Raises ValueError on malformed input."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    text = s.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a strict yyyy-mm-dd calendar date. Raises ValueError otherwise."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    text = s.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        raise ValueError("not a yyyy-mm-dd date")
    return date.fromisoformat(text)
