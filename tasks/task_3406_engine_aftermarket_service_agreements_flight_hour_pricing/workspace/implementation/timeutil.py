"""Time helpers: ISO-8601 parsing/formatting, month arithmetic, YYYY-MM periods.

All domain datetimes are aware UTC. Formatting uses three fractional digits and
a Z suffix exactly as PRD 2.5 shows (e.g. 2026-09-01T00:00:00.000Z).
"""
import calendar
from datetime import datetime, timezone

from errors import api_err


def parse_iso(value):
    """Parse an ISO-8601 datetime string to an aware UTC datetime.

    Raises ValueError on any malformed input. Naive inputs are treated as UTC.
    """
    if not isinstance(value, str):
        raise ValueError("datetime must be an ISO-8601 string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Render an aware datetime as ISO-8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def add_months(dt, months):
    """Add calendar months, clamping the day to the target month's last day."""
    total = (dt.year * 12 + (dt.month - 1)) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def parse_period(value):
    """'YYYY-MM' -> (year, month). Raises ValueError on malformed input."""
    if not isinstance(value, str):
        raise ValueError("period must be a YYYY-MM string")
    parts = value.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise ValueError("period must be a YYYY-MM string")
    if not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError("period must be a YYYY-MM string")
    year = int(parts[0])
    month = int(parts[1])
    if not (1 <= month <= 12):
        raise ValueError("period month out of range")
    return (year, month)


def period_index(pt):
    """Monotonic month index for a (year, month) tuple."""
    return pt[0] * 12 + pt[1]


def tuple_from_index(k):
    """Inverse of period_index (month is 1-based)."""
    y, m = divmod(k, 12)
    if m == 0:
        return (y - 1, 12)
    return (y, m)


def period_end_instant(pt):
    """Last representable instant of the period month (used by escalation)."""
    year, month = pt
    last = calendar.monthrange(year, month)[1]
    return datetime(year, month, last, 23, 59, 59, 999999, tzinfo=timezone.utc)


def clock_period(dt):
    return (dt.year, dt.month)


def check_not_future_period(pt, clock):
    """PRD 2.4: a period after the current logical-clock month -> 422."""
    if period_index(pt) > period_index(clock_period(clock)):
        raise api_err("ERR_FUTURE_PERIOD", "period is after the current logical-clock month")
