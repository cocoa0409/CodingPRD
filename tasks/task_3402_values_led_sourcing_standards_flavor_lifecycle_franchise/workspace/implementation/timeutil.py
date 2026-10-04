"""Time parsing/formatting helpers shared by the logical clock and payloads."""
from datetime import datetime, timezone


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset; naive values are assumed UTC.
    Raises ValueError on malformed input.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if v.endswith(("Z", "z")):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with a Z suffix.

    Whole-second values render as 'yyyy-mm-ddTHH:MM:SSZ'; fractional seconds
    are preserved (trailing zeros trimmed).
    """
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        base = dt.strftime("%Y-%m-%dT%H:%M:%S")
        frac = ("%06d" % dt.microsecond).rstrip("0")
        return "%s.%sZ" % (base, frac)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_wall(dt):
    """Wall-clock timestamp: ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"
