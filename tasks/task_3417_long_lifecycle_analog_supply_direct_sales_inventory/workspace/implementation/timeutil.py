# ISO-8601 UTC helpers. All stored datetimes are tz-aware UTC.
from datetime import datetime, timezone


def parse_iso(value):
    """Parse an ISO8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Format an aware datetime as ISO8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_years(dt, n):
    """dt shifted by n whole years; Feb 29 collapses to Feb 28."""
    try:
        return dt.replace(year=dt.year + n)
    except ValueError:
        return dt.replace(year=dt.year + n, day=28)


def years_elapsed(start, now):
    """Number of complete 12-month anniversaries of start at or before now."""
    n = 0
    while add_years(start, n + 1) <= now:
        n += 1
    return n
