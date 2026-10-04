"""Logical clock (PRD §2.4).

Startup default is exactly 2026-09-01T00:00:00Z; the clock never falls back to
wall-clock time. Every stamped timestamp and every window/expiry comparison
reads this clock.
"""
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"


def parse_dt(s):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_now = parse_dt(DEFAULT_CLOCK_UTC)


def now_dt():
    return _now


def set_now(dt):
    global _now
    _now = dt


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(_now)


def add_years(dt, years):
    """Add calendar years (Feb 29 clamps to Feb 28)."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, month=2, day=28)


def add_days(dt, days):
    return dt + timedelta(days=days)
