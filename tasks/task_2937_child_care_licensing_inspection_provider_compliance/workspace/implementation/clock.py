"""The logical licensing clock (PRD §2.4). Nothing here reads the wall clock."""

import calendar
import datetime as _dt
import re

from constants import DEFAULT_LOGICAL_CLOCK

UTC = _dt.timezone.utc

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(value):
    """Parse an ISO-8601 instant into an aware UTC datetime. None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    if second > 59 or minute > 59 or hour > 23:
        return None
    try:
        naive = _dt.datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if tz in (None, "Z", "z"):
        return naive.replace(tzinfo=UTC)
    sign = 1 if tz[0] == "+" else -1
    body = tz[1:].replace(":", "")
    off = _dt.timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * off).replace(tzinfo=UTC)


def parse_date(value):
    """Parse a calendar date in year-month-day form. None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt(dt):
    """Render an aware datetime as an ISO-8601 UTC instant with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


class _Clock(object):
    def __init__(self):
        self.value = parse_instant(DEFAULT_LOGICAL_CLOCK)

    def set(self, dt):
        self.value = dt


CLOCK = _Clock()


def now_dt():
    return CLOCK.value


def now():
    return fmt(CLOCK.value)


def set_clock(dt):
    CLOCK.set(dt)
    return fmt(CLOCK.value)


def add_days(dt, days):
    return dt + _dt.timedelta(days=days)


def add_hours(dt, hours):
    return dt + _dt.timedelta(hours=hours)


def add_minutes(dt, minutes):
    return dt + _dt.timedelta(minutes=minutes)


def add_months(dt, months):
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def sub_months(dt, months):
    return add_months(dt, -months)


def at(value):
    """Canonicalise a stored instant string into an aware datetime."""
    return parse_instant(value)
