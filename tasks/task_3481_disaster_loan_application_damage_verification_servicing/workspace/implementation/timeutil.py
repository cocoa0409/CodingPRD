"""Datetime parsing/formatting helpers. All entity timestamps use the logical clock."""

from datetime import datetime, timedelta, timezone


def parse_dt(value):
    """Parse an ISO-8601 string (date or datetime, optional Z) to an aware UTC datetime.

    Returns None when the value is not a parseable datetime string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_wall():
    return datetime.now(timezone.utc)


def add_months(dt, months):
    """Calendar-month addition with day clamping (e.g. Jan 31 + 1 -> Feb 28)."""
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    if m == 12:
        first_next = datetime(y + 1, 1, 1)
    else:
        first_next = datetime(y, m + 1, 1)
    last_day = (first_next - timedelta(days=1)).day
    return dt.replace(year=y, month=m, day=min(dt.day, last_day))


def days_between(a, b):
    """Calendar days from date a to date b (b - a), by calendar date."""
    return (b.date() - a.date()).days
