"""Logical UTC clock (PRD section 2.4).

Startup value is exactly 2026-08-01T00:00:00Z; the server never falls back to
wall-clock time.
"""
import re
from datetime import datetime, timedelta, timezone

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock(object):
    def __init__(self):
        self.now = _START

    def reset(self):
        self.now = _START

    def set(self, dt):
        self.now = dt.astimezone(timezone.utc)


clock = Clock()


def parse_instant(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    tzpart = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if tzpart is None or tzpart in ("Z", "z"):
        return base.replace(tzinfo=timezone.utc)
    sign = 1 if tzpart[0] == "+" else -1
    body = tzpart[1:].replace(":", "")
    offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4])) * sign
    return (base - offset).replace(tzinfo=timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date. Returns a date or None."""
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def now():
    return clock.now


def now_iso():
    return fmt_instant(clock.now)


def now_date():
    return clock.now.date()


def now_date_iso():
    return fmt_date(clock.now.date())


def add_calendar_years(d, years):
    """Add whole calendar years; a Feb-29 anniversary clamps down to Feb 28."""
    year = d.year + years
    month = d.month
    day = d.day
    if month == 2 and day == 29:
        if not _is_leap(year):
            day = 28
    return d.replace(year=year, month=month, day=day)


def _is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
