"""ISO-8601 helpers.  All instants are UTC and serialised with exactly three
fractional-second digits (PRD section 2.4)."""

import re
from datetime import datetime, timezone, timedelta, date

DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(value):
    """Parse an ISO-8601 instant.  Returns a tz-aware UTC datetime truncated to
    millisecond precision, or None when the text is not a parseable instant."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    m = _INSTANT_RE.match(text)
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    off = m.group(8)
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        digits = off[1:].replace(":", "")
        delta = timedelta(hours=int(digits[:2]), minutes=int(digits[2:4]))
        dt = dt - sign * delta
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date; returns a date or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt(dt):
    """Serialise a datetime as ISO-8601 UTC with exactly three fractional digits."""
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


def day_start(d):
    """Midnight UTC at the start of the given calendar date."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def week_anchor(dt):
    """The Monday 00:00:00.000Z at or before the given instant (PRD section 2.10)."""
    dt = dt.astimezone(timezone.utc)
    monday = dt - timedelta(days=dt.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def overlaps(start_a, end_a, start_b, end_b):
    """Half-open interval overlap: each start strictly before the other's end."""
    return start_a < end_b and start_b < end_a


def whole_days_between(earlier, later):
    """Whole days from earlier to later (floor of the elapsed duration)."""
    return int((later - earlier).total_seconds() // 86400)


def now_wall():
    dt = datetime.now(timezone.utc)
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)
