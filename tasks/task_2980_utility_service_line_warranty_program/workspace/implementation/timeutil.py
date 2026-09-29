"""Instant / calendar-date parsing, rendering and arithmetic.

Instants are ISO 8601 UTC rendered with exactly three fractional-second digits.
Calendar dates are plain YYYY-MM-DD with no time component at all.  Every
temporal comparison in the service is done on these two types only; there is no
wall clock anywhere in the implementation.
"""

import calendar
import re
from datetime import date, datetime, timedelta, timezone

INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.(\d{1,9}))?(?:[Zz]|[+-]00:?00)$"
)
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(value):
    """Parse an ISO 8601 UTC instant. Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    m = INSTANT_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(8) or "0"
    micro = int((frac + "000000")[:6])
    try:
        return datetime(
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
            int(m.group(4)),
            int(m.group(5)),
            int(m.group(6)),
            micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def parse_date(value):
    """Parse a plain calendar date. Returns a date or None."""
    if not isinstance(value, str):
        return None
    m = DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def render_instant(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        millis,
    )


def render_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def instant_to_date(dt):
    """The calendar date an instant falls on, in UTC."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).date()


def date_to_instant(d):
    """Midnight UTC on a calendar date."""
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def add_days(d, days):
    return d + timedelta(days=days)


def add_months(d, months):
    """Whole-calendar-month arithmetic: same day-of-month, clamped to month end."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_years(d, years):
    return add_months(d, 12 * years)


def whole_days_between(start, end):
    """Signed count of whole calendar days from start to end."""
    return (end - start).days


def days_in_month(d):
    return calendar.monthrange(d.year, d.month)[1]


def month_start(d):
    return date(d.year, d.month, 1)


def next_month_start(d):
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def floor_minutes_between(start, end):
    """Whole minutes elapsed, truncated toward zero."""
    return int((end - start).total_seconds() // 60)


def floor_days_between_instants(start, end):
    """Whole days elapsed between two instants, truncated toward zero."""
    seconds = (end - start).total_seconds()
    return int(seconds // 86400) if seconds >= 0 else -int((-seconds) // 86400)
