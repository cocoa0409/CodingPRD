"""Logical clock, week index, and ISO-8601 timestamp helpers."""
from datetime import datetime, timezone

from db import store

# Retail week anchor: Monday 2026-01-05T00:00:00Z.
WEEK_EPOCH = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
COLORS = ["BLUE", "GREEN", "YELLOW", "RED"]


def now():
    return store.clock


def set_now(dt):
    store.clock = dt


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def week_index(dt=None):
    """Whole seven-day periods fully elapsed since WEEK_EPOCH (floor)."""
    dt = dt or now()
    delta = dt - WEEK_EPOCH
    return delta.days // 7
