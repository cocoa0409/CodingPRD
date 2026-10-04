"""ISO8601 time helpers. All instants are timezone-aware UTC."""

import calendar
from datetime import datetime, timezone

UTC = timezone.utc


def parse_iso(value):
    """Parse an ISO8601 string (date-only or datetime, 'Z' or numeric offset)
    into an aware UTC datetime. Naive input is treated as UTC.
    Raises ValueError on unparseable input."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty timestamp")
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    if "T" not in s and "t" not in s:
        s = s + "T00:00:00+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt(dt):
    """Format an aware datetime as ISO8601 UTC with three fractional digits
    and a trailing Z, e.g. 2026-09-01T00:00:00.000Z."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_months(dt, months):
    """Add whole calendar months, clamping the day-of-month to the target
    month's length (e.g. Oct 31 + 4 months -> Feb 28/29)."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)
