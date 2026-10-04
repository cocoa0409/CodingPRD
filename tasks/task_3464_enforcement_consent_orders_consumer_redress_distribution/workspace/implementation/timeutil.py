"""Logical-time helpers: ISO8601 parsing/formatting, second-precision comparison."""
from datetime import datetime, timezone, timedelta


def parse_iso(value):
    """Parse an ISO8601 string (with Z or numeric offset) to an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("empty timestamp")
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    else:
        raise ValueError("not an ISO8601 string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_iso(value):
    try:
        parse_iso(value)
        return True
    except (ValueError, TypeError):
        return False


def fmt_iso(dt):
    """Format an aware datetime as ISO8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def seconds(dt):
    """Truncate a datetime to whole-second precision (PRD: comparisons at second precision)."""
    return dt.replace(microsecond=0)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap target years
        return dt.replace(year=dt.year + years, day=28)
