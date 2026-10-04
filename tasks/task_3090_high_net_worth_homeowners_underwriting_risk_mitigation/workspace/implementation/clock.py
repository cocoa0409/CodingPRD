"""Logical clock and temporal helpers.

The platform never reads the host wall clock (PRD §2.4).  A single logical
clock pinned to 2026-09-01T00:00:00Z at startup is the only source of "now";
it moves solely through POST /hnw/_clock/set_current_utc.
"""

from datetime import datetime, timedelta, timezone

STARTUP_UTC = "2026-09-01T00:00:00Z"


class Clock:
    """Mutable holder for the logical instant."""

    def __init__(self, initial=STARTUP_UTC):
        self._now = parse_dt(initial)

    @property
    def now(self):
        return self._now

    def set(self, value):
        self._now = parse_dt(value)
        return self._now


def _utc(dt):
    """Normalize to an aware UTC datetime, accepting ISO strings too."""
    if isinstance(dt, str):
        dt = parse_dt(dt)
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_dt(value, default=None):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if value is None:
        return default
    if isinstance(value, datetime):
        return _utc(value)
    if not isinstance(value, str):
        return default
    text = value.strip()
    if not text:
        return default
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        return _utc(datetime.fromisoformat(text))
    except ValueError:
        return default


def fmt_dt(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    if dt is None:
        return None
    dt = _utc(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def months_between(start, end):
    """Whole calendar months from ``start`` to ``end`` (never rounded up)."""
    if start is None or end is None:
        return 0
    start = _utc(start)
    end = _utc(end)
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    if months < 0:
        months = 0
    return months


def days_between_exclusive_inclusive(start, end):
    """Whole days, exclusive of ``start`` and inclusive of ``end`` (PRD §3.9)."""
    if start is None or end is None:
        return 0
    return (_utc(end).date() - _utc(start).date()).days


def whole_days_ago(then, now):
    """Whole-day floor of the elapsed time from ``then`` to ``now``."""
    if then is None or now is None:
        return 0
    delta = _utc(now) - _utc(then)
    return int(delta.total_seconds() // 86400)


def add_months(dt, months):
    """Advance ``dt`` by whole calendar months, clamping the day-of-month."""
    dt = _utc(dt)
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def _days_in_month(year, month):
    if month == 12:
        return 31
    nxt = datetime(year, month + 1, 1)
    return (nxt - datetime(year, month, 1)).days


def first_of_next_month(dt):
    dt = _utc(dt)
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1, day=1,
                          hour=0, minute=0, second=0, microsecond=0)
    return dt.replace(month=dt.month + 1, day=1,
                      hour=0, minute=0, second=0, microsecond=0)


def add_days(dt, days):
    return _utc(dt) + timedelta(days=days)


def add_hours(dt, hours):
    return _utc(dt) + timedelta(hours=hours)