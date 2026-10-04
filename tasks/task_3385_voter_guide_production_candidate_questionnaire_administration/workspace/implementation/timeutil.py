"""Temporal parsing / formatting.

Instants are aware UTC datetimes. Rendered timestamps are ISO 8601 UTC with
three fractional digits, e.g. 2026-09-01T00:00:00.000Z (PRD 2.5).
"""
import re
from datetime import date, datetime, timezone

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_instant(value):
    """Parse an ISO 8601 instant. Raises ValueError when malformed."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
    v = datetime.fromisoformat(iso)
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        raise ValueError("not a YYYY-MM-DD date")
    return date.fromisoformat(value.strip())


def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    if isinstance(d, date):
        return d.isoformat()
    return d
