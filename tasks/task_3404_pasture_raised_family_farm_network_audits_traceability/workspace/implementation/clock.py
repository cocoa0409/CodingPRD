"""Server-owned logical clock (PRD 2.5).

The server never reads wall-clock time. It boots at 2026-09-01T00:00:00Z and
advances only via POST /farm-network/_clock/set_current_utc. Every timestamp
the server writes is read from this clock and serialized as ISO 8601 UTC with
three fractional digits.
"""
import re
from datetime import datetime, date, timezone

from constants import CLOCK_BOOT_ISO

_current = None


def boot():
    global _current
    _current = parse_datetime(CLOCK_BOOT_ISO)


def now():
    return _current


def set_current(dt):
    global _current
    _current = dt


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Strict YYYY-MM-DD -> date, or None when invalid."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_datetime(value):
    """ISO 8601 -> aware UTC datetime, or None when invalid.

    Accepts a trailing Z/z or a numeric offset; naive values are read as UTC.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_ms(dt):
    """datetime -> 'YYYY-MM-DDTHH:MM:SS.mmmZ' (PRD 2.2 timestamp format)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))
