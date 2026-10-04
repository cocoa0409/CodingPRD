"""ISO8601 helpers. All instants are timezone-aware UTC.
Entity timestamps are emitted with exactly three fractional digits and a Z suffix.
"""
from datetime import datetime, timezone


def parse_iso(s):
    """Parse an ISO8601 timestamp string into an aware UTC datetime.
    Accepts a trailing 'Z' or numeric offset; naive values are treated as UTC.
    Raises ValueError on malformed input."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if not t:
        raise ValueError("empty timestamp")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a strict YYYY-MM-DD calendar date into midnight UTC."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    dt = datetime.strptime(s.strip(), "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def is_date_str(s):
    try:
        parse_date(s)
        return True
    except (ValueError, AttributeError):
        return False


def fmt(dt):
    """Format an aware datetime as ISO8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def try_parse_iso(s):
    try:
        return parse_iso(s)
    except (ValueError, AttributeError, TypeError):
        return None
