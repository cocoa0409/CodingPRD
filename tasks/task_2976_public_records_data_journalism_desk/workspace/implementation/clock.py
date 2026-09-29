"""Logical clock (PRD section 2.6).

Nothing in this service reads wall-clock time.  The logical clock starts at
2026-08-01T00:00:00Z on every fresh boot and only moves when
POST /_clock/set_current_utc says so.
"""
import re
from datetime import datetime, timezone, date, timedelta

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_STATE = {"now": DEFAULT_NOW}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def now():
    return _STATE["now"]


def set_now(dt):
    _STATE["now"] = dt.astimezone(timezone.utc)
    return _STATE["now"]


def reset():
    _STATE["now"] = DEFAULT_NOW


def iso(dt):
    """ISO-8601 UTC with exactly three fractional-second digits and a Z suffix."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    d = dt.astimezone(timezone.utc)
    millis = d.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        d.year, d.month, d.day, d.hour, d.minute, d.second, millis,
    )


def now_iso():
    return iso(now())


def parse_instant(value):
    """Parse an ISO-8601 instant.  Returns an aware UTC datetime or None on failure."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    # tolerate more than 6 fractional digits
    m = re.match(r"^(.*\.\d{6})\d+(.*)$", text)
    if m:
        text = m.group(1) + m.group(2)
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a plain YYYY-MM-DD calendar date.  Returns a date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def utc_date(dt):
    return dt.astimezone(timezone.utc).date()


def end_of_day_iso(d):
    """A calendar date rendered as that date's final second: T23:59:59.000Z."""
    return "%04d-%02d-%02dT23:59:59.000Z" % (d.year, d.month, d.day)


def instant_of(iso_string):
    """Convenience: parse a stored canonical instant string."""
    if iso_string is None:
        return None
    return parse_instant(iso_string)


def hours_between(earlier, later):
    """Exact elapsed hours between two aware datetimes as a float."""
    delta = later - earlier
    return delta.total_seconds() / 3600.0


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
