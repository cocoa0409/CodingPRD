"""Datetime parsing/formatting helpers.

Entity/logical-clock datetimes are stored internally as tz-aware UTC datetimes
and serialized as ISO 8601 with a trailing Z (no fractional part when the value
is a whole second, so an echoed date matches what the client supplied).
"""
from datetime import datetime, timezone


def parse_dt(value):
    """Parse an ISO 8601 string; date-only values land at midnight UTC."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        s = s + "T00:00:00Z"
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def whole_days(start_dt, end_dt):
    """Whole calendar days in the half-open interval [start_dt, end_dt)."""
    return (end_dt.date() - start_dt.date()).days
