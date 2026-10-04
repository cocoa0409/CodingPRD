"""Logical clock (PRD section 2.5).

Startup default is exactly 2026-09-01T00:00:00Z and it never falls back to
wall-clock time. All temporal reasoning in the system uses this clock.
"""
import calendar as _cal
from datetime import datetime, date, timezone

_DEFAULT = "2026-09-01T00:00:00Z"
_state = {
    "dt": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc),
    "str": _DEFAULT,
}


def parse_iso(s):
    """Parse an ISO 8601 timestamp (accepts trailing Z or numeric offset)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    return _state["dt"]


def today():
    return _state["dt"].date()


def now_str():
    """The clock as last supplied (echo format); default 2026-09-01T00:00:00Z."""
    return _state["str"]


def set_clock(s):
    dt = parse_iso(s)
    _state["dt"] = dt
    _state["str"] = s
    return s


def stamp():
    """Entity timestamp: ISO 8601 UTC with three fractional digits."""
    dt = _state["dt"]
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_months(d, months):
    """Add whole months to a date/datetime, clamping the day of month."""
    idx = (d.year * 12 + (d.month - 1)) + months
    y, m = idx // 12, idx % 12 + 1
    last = _cal.monthrange(y, m)[1]
    day = min(d.day, last)
    if isinstance(d, datetime):
        return d.replace(year=y, month=m, day=day)
    return date(y, m, day)


def whole_months_between(start, cur):
    """Whole calendar months elapsed from start date to cur date."""
    m = (cur.year - start.year) * 12 + (cur.month - start.month)
    if cur.day < start.day:
        m -= 1
    return m
