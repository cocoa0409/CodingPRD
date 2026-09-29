"""Logical clock and time helpers.

PRD 2.5: "The service never reads wall-clock time. It maintains a logical clock
which, before any client has set it, reads exactly 2026-08-01T00:00:00Z, and
which is advanced only by an administrator-only test-driving capability".
"""
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
QUARTER_START_MONTHS = (1, 4, 7, 10)

_current = DEFAULT_CLOCK


def now():
    return _current


def set_now(value):
    global _current
    _current = value
    return _current


def reset():
    global _current
    _current = DEFAULT_CLOCK


def fmt(value):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.4)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        v = value.astimezone(timezone.utc)
        return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
            v.year, v.month, v.day, v.hour, v.minute, v.second,
            v.microsecond // 1000,
        )
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def parse_datetime(raw):
    """Parse an ISO-8601 instant. Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_date(raw):
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def add_days(value, days):
    return value + timedelta(days=int(days))


def add_hours(value, hours):
    """Advance an instant by a (possibly fractional) number of hours."""
    micros = (Decimal(str(hours)) * Decimal(3600) * Decimal(1000000)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return value + timedelta(microseconds=int(micros))


def quarter_end_instant(value):
    """First instant of the calendar quarter that follows `value` (PRD 2.5)."""
    year = value.year
    for month in QUARTER_START_MONTHS:
        candidate = datetime(year, month, 1, tzinfo=timezone.utc)
        if candidate > value:
            return candidate
    return datetime(year + 1, 1, 1, tzinfo=timezone.utc)


def surge_window_start(value, surge_window_days):
    return quarter_end_instant(value) - timedelta(days=int(surge_window_days))


def in_surge_window(value, surge_window_days):
    """Start boundary inclusive, quarter-end instant exclusive (PRD 2.5)."""
    end = quarter_end_instant(value)
    start = end - timedelta(days=int(surge_window_days))
    return start <= value < end


def hours_between(start, end):
    delta = end - start
    seconds = Decimal(delta.days) * Decimal(86400) + Decimal(delta.seconds) + (
        Decimal(delta.microseconds) / Decimal(1000000)
    )
    return seconds / Decimal(3600)
