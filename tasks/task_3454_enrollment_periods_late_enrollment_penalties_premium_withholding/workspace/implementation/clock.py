"""Logical clock and calendar-month arithmetic.

The system runs on a logical clock, never wall-clock. Before any
POST /_clock/set_current_utc call the clock reads exactly
2026-09-01T00:00:00Z.
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

_state = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now() -> datetime:
    return _state["now"]


def set_now(dt: datetime) -> None:
    _state["now"] = dt


def parse_iso8601(s) -> datetime:
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_ts(dt: datetime) -> str:
    """ISO 8601 UTC timestamp with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def format_clock_reading(dt: datetime) -> str:
    """Canonical clock reading: seconds precision when exact, else millis."""
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return format_ts(dt)


def clock_month():
    """The UTC year-month of the current logical-clock reading, as (y, m)."""
    n = now()
    return (n.year, n.month)


def clock_date() -> date:
    return now().date()


_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_month(s):
    """Parse a YYYY-MM month string into a (year, month) tuple."""
    if not isinstance(s, str):
        raise ValueError("not a month string")
    m = _MONTH_RE.match(s.strip())
    if not m:
        raise ValueError("bad month format")
    y, mo = int(m.group(1)), int(m.group(2))
    if mo < 1 or mo > 12:
        raise ValueError("month out of range")
    return (y, mo)


def month_str(ym) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


def add_months(ym, n: int):
    y, m = ym
    total = y * 12 + (m - 1) + n
    return (total // 12, total % 12 + 1)


def month_diff(a, b) -> int:
    """a - b in whole calendar months."""
    return (a[0] - b[0]) * 12 + (a[1] - b[1])


def iter_months(a, b):
    """Yield every month in the inclusive range [a, b]."""
    if month_diff(b, a) < 0:
        return
    cur = a
    while cur <= b:
        yield cur
        cur = add_months(cur, 1)


def parse_date(s) -> date:
    """Parse a strict YYYY-MM-DD calendar date."""
    if not isinstance(s, str):
        raise ValueError("not a date string")
    m = _DATE_RE.match(s.strip())
    if not m:
        raise ValueError("bad date format")
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return date(y, mo, d)  # raises ValueError on impossible dates


def parse_due_date(s) -> date:
    return parse_date(s)


def last_day_of_month(ym) -> date:
    y, m = ym
    return date(y, m, monthrange(y, m)[1])


def days_after(d: date, n: int) -> date:
    return d + timedelta(days=n)
