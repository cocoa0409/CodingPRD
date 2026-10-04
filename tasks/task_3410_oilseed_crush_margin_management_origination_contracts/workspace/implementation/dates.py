"""Datetime parsing and calendar helpers."""
import re
from datetime import datetime, timezone

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def parse_iso(value):
    """Parse an ISO 8601 datetime (accepts trailing Z, offsets, date-only).
    Returns an aware UTC datetime, or None if unparseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def valid_month(s):
    return isinstance(s, str) and bool(MONTH_RE.match(s))


def days_between(d1, d2):
    """Whole UTC calendar days from d1 to d2 (date parts only)."""
    return (d2.date() - d1.date()).days


def months_between(m1, m2):
    """(year2-year1)*12 + (month2-month1) for YYYY-MM strings."""
    y1, mo1 = int(m1[:4]), int(m1[5:7])
    y2, mo2 = int(m2[:4]), int(m2[5:7])
    return (y2 - y1) * 12 + (mo2 - mo1)
