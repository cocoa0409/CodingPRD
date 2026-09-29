"""Logical clock. PRD 2.4: startup default is exactly 2026-08-01T00:00:00Z and the
server must never fall back to real wall-clock time."""
import calendar
import re
from datetime import datetime, timezone, timedelta, date

DEFAULT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_state = {"now": DEFAULT_INSTANT}


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_instant(value):
    """Returns an aware datetime, or None when the string is not a legal instant."""
    if not isinstance(value, str) or not _INSTANT_RE.match(value):
        return None
    body = value[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        micro = int((frac + "000000")[:6])
    else:
        head, micro = body, 0
    try:
        base = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return base.replace(microsecond=micro, tzinfo=timezone.utc)


def parse_date(value):
    """Returns a date, or None when the string is not a legal date-only value."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def now():
    return _state["now"]


def now_iso():
    return fmt_instant(_state["now"])


def today():
    return _state["now"].date()


def set_now(dt):
    _state["now"] = dt
    return _state["now"]


def reset():
    _state["now"] = DEFAULT_INSTANT


def days_in_month(d):
    return calendar.monthrange(d.year, d.month)[1]


def first_of_month(d):
    return date(d.year, d.month, 1)


def last_of_month(d):
    return date(d.year, d.month, days_in_month(d))


def plus_days(d, n):
    return d + timedelta(days=n)
