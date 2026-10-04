"""§2.4 The logical clock.

Every deadline, window, expiry and shelf-life rule reads this value. It never
falls back to wall-clock time.
"""

from datetime import datetime, timedelta, timezone

from common import DEFAULT_LOGICAL_CLOCK

_CLOCK = {"now": datetime(2026, 9, 1, tzinfo=timezone.utc)}


def parse_instant(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if value is None:
        raise ValueError("missing instant")
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO 8601 calendar date (or the date half of an instant)."""
    if value is None:
        raise ValueError("missing date")
    text = str(value).strip()
    if "T" in text:
        return parse_instant(text).date()
    return datetime.fromisoformat(text).date()


def now():
    return _CLOCK["now"]


def set_now(dt):
    _CLOCK["now"] = dt


def format_instant(dt):
    """ISO 8601 UTC with three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (dt.astimezone(timezone.utc).microsecond // 1000)


def now_iso():
    return format_instant(now())


def default_clock_iso():
    return DEFAULT_LOGICAL_CLOCK


def plus_days(dt, days):
    return dt + timedelta(days=days)


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def days_between(start_date, end_date):
    """Whole days between two calendar dates, counting neither boundary."""
    return (end_date - start_date).days