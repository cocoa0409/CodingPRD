"""Deterministic logical clock plus date / instant helpers (PRD section 2.5, 2.4)."""

import re
from datetime import datetime, timedelta, timezone, date as _date

BOOT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2})(?::(\d{2}))?(\.\d{1,9})?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

_state = {"now": BOOT_INSTANT, "raw": None}


def now():
    return _state["now"]


def today():
    return _state["now"].date()


def set_now(instant, raw=None):
    _state["now"] = instant
    _state["raw"] = raw


def raw_current():
    return _state["raw"] if _state["raw"] is not None else fmt_instant(BOOT_INSTANT)


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000
    )


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_instant(value):
    """Parse an ISO 8601 instant. Raises ValueError when malformed."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _INSTANT_RE.match(value.strip())
    if not m:
        raise ValueError("malformed instant")
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    tz = m.group(8)
    dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


def parse_date(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _DATE_RE.match(value.strip())
    if not m:
        raise ValueError("malformed date")
    return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def add_days(value, days):
    return value + timedelta(days=days)


def add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def is_business_day(d):
    return d.weekday() < 5


def next_business_day(d):
    out = d
    while not is_business_day(out):
        out = out + timedelta(days=1)
    return out


def advance_business_days(d, count):
    """Move forward `count` business days (Mon-Fri, no holiday calendar)."""
    out = d
    moved = 0
    while moved < count:
        out = out + timedelta(days=1)
        if is_business_day(out):
            moved += 1
    return out


def whole_years_between(start, reference):
    """Whole completed years; an exact anniversary counts."""
    if reference < start:
        return 0
    years = reference.year - start.year
    if (reference.month, reference.day) < (start.month, start.day):
        years -= 1
    return max(0, years)


def end_of_day(d):
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)
