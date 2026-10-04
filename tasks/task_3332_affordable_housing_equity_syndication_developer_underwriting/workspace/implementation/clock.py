"""Logical clock and timestamp helpers.

The system never observes wall-clock time.  At startup the logical clock reads
exactly 2026-09-01T00:00:00Z and it stays there until a PlatformAdmin advances
it through POST /_clock/set_current_utc (PRD 2.4).
"""

from datetime import datetime, timedelta, timezone

# Startup default instant — the only piece of state the process begins with.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# The clock is process-global and reset by every fresh boot.
_current = None


def _parse(value):
    """Parse an ISO 8601 instant, tolerating a trailing Z."""
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset():
    global _current
    _current = _parse(DEFAULT_CLOCK)
    return _current


def now():
    """The current logical instant."""
    if _current is None:
        reset()
    return _current


def set_now(value):
    global _current
    _current = _parse(value)
    return _current


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = _parse(dt)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_str():
    return fmt(now())


def add_months(dt, months):
    """Add a whole number of months, clamping the day to the month length."""
    month_index = dt.month - 1 + int(months)
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp to the last valid day of the target month.
    if month == 12:
        last_day = 31
    else:
        last_day = (datetime(year, month + 1, 1) - timedelta(days=1)).day
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def add_days(dt, days):
    return dt + timedelta(days=int(days))
