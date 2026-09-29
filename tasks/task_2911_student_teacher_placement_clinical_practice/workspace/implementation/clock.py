"""The logical clock (PRD 2.5) plus strict ISO-8601 parsing / formatting."""

import re
from datetime import datetime, date, timedelta, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_CLOCK}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)


def now():
    """Current logical-clock instant (timezone aware, UTC)."""
    return _state["now"]


def today():
    """Date component of the logical clock."""
    return _state["now"].date()


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)


def reset():
    _state["now"] = DEFAULT_CLOCK


def parse_date(value):
    """Strict YYYY-MM-DD -> datetime.date; None when malformed."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_instant(value):
    """Strict ISO-8601 UTC instant -> aware datetime; None when malformed."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value)
    if not m:
        return None
    frac = m.group(7) or ""
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    off = m.group(8)
    try:
        naive = datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)), micro,
        )
    except ValueError:
        return None
    if off in ("Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if off[0] == "+" else -1
    delta = timedelta(hours=int(off[1:3]), minutes=int(off[4:6])) * sign
    return (naive - delta).replace(tzinfo=timezone.utc)


def fmt_instant(dt):
    """ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def end_of_day(d):
    """The 23:59:59Z instant of a calendar date."""
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)
