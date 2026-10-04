"""Time helpers: ISO8601 UTC parsing/formatting (3 fractional digits) and
calendar arithmetic for the logical clock."""
import re
from datetime import datetime, timedelta, timezone

from constants import CLOCK_START_ISO

_MM_DD_RE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")


def clock_start():
    """The fixed logical-clock startup instant (PRD §2.4)."""
    return parse_iso(CLOCK_START_ISO)


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit numeric offset, with or without
    fractional seconds. Returns None when the value is not a valid timestamp.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly 3 fractional
    digits, e.g. 2026-09-01T00:00:00.000Z (PRD §2.5)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def valid_mm_dd(value):
    """True when value is a well-formed MM-DD fiscal-year-end string."""
    return isinstance(value, str) and _MM_DD_RE.match(value) is not None


def mm_dd_in_year(mm_dd, year):
    """The MM-DD anchor at 00:00:00Z in the given calendar year."""
    month, day = int(mm_dd[:2]), int(mm_dd[3:5])
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        # Feb 29 in a non-leap year: clamp to Feb 28 (deterministic).
        return datetime(year, 2, 28, tzinfo=timezone.utc)


def plus_one_year(dt):
    """Same month-day at 00:00:00Z, one calendar year later."""
    try:
        return dt.replace(year=dt.year + 1)
    except ValueError:
        # Feb 29 -> Feb 28 of the following (non-leap) year.
        return dt.replace(year=dt.year + 1, day=28)
