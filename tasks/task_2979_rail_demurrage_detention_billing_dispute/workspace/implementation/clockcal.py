"""Instant parsing/formatting and the three day calendars of PRD §2.5.

  * eligible date  - tariff dependent (weekend_excluded)
  * business date  - Monday..Friday, unconditional
  * calendar date  - every date

Every computed deadline lands on the last representable millisecond of its
date, namely 23:59:59.999Z (PRD §2.4).
"""

import re
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc

# ISO 8601 with an explicit Z designator.  Anything else is a schema violation.
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?[Zz]$"
)

MS_PER_DAY = 86400000
MS_PER_HOUR = 3600000


def parse_instant(value):
    """Return an aware datetime, or None when the value is not a Z-suffixed
    ISO 8601 instant."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7) or ""
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=UTC,
        )
    except ValueError:
        return None


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def host_now_iso():
    return fmt_instant(datetime.now(UTC))


def date_of(dt):
    return dt.astimezone(UTC).date()


def eod(d):
    """Last representable millisecond of a UTC date: 23:59:59.999Z."""
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=UTC)


def month_key(dt):
    d = date_of(dt)
    return "%04d-%02d" % (d.year, d.month)


# --------------------------------------------------------------------------
# calendars
# --------------------------------------------------------------------------

def is_business(d):
    return d.weekday() < 5


def is_eligible(d, weekend_excluded):
    if weekend_excluded:
        return d.weekday() < 5
    return True


def nth_eligible(start, n, weekend_excluded):
    """The nth eligible date after `start`.  n == 0 is `start` itself; for any
    n >= 1 the answer is strictly later than `start` (PRD §2.5)."""
    if n <= 0:
        return start
    cur = start
    seen = 0
    while seen < n:
        cur = cur + timedelta(days=1)
        if is_eligible(cur, weekend_excluded):
            seen += 1
    return cur


def nth_business(start, n):
    """The nth business date (Mon-Fri) strictly after `start`; n == 0 returns
    `start` itself."""
    if n <= 0:
        return start
    cur = start
    seen = 0
    while seen < n:
        cur = cur + timedelta(days=1)
        if is_business(cur):
            seen += 1
    return cur


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_days(d, n):
    return d + timedelta(days=n)


def dates_between(first, last):
    """Inclusive ascending walk of calendar dates."""
    out = []
    cur = first
    while cur <= last:
        out.append(cur)
        cur = cur + timedelta(days=1)
    return out


def date_span_count(first, last):
    if last < first:
        return 0
    return (last - first).days + 1


def whole_ms(delta):
    """Whole milliseconds in a timedelta, computed exactly (no float)."""
    return delta // timedelta(milliseconds=1)


COLD_START_CLOCK = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)

__all__ = [
    "UTC", "MS_PER_DAY", "MS_PER_HOUR", "COLD_START_CLOCK", "date", "datetime",
    "timedelta", "parse_instant", "fmt_instant", "host_now_iso", "date_of",
    "eod", "month_key", "is_business", "is_eligible", "nth_eligible",
    "nth_business", "add_hours", "add_minutes", "add_days", "dates_between",
    "date_span_count", "whole_ms",
]
