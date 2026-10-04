"""The deterministic logical clock.

Time in this API is never read from the wall.  Before any clock-setting call the
clock reads the fixed instant 2026-09-01T00:00:00Z (PRD §2.11), and it never
falls back to wall-clock time, so every refresh-interval projection, release
window comparison and dispatch boundary is reproducible from the call sequence
alone.
"""

from datetime import datetime, timedelta, timezone

DEFAULT_CURRENT_UTC = "2026-09-01T00:00:00Z"
# The analytics-snapshot dispatch instant (PRD §3.8).
SNAPSHOT_DISPATCH_AT = "2026-10-05T00:00:00Z"


def now():
    """The current logical instant."""
    return _CURRENT[0]


def set_now(dt):
    _CURRENT[0] = dt
    return _CURRENT[0]


def add_days(dt, days):
    return dt + timedelta(days=days)


def day_delta(later, earlier):
    """Whole logical days between two instants (inth truncated toward zero)."""
    return int((later - earlier).total_seconds() // 86400)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits.

    Tolerates values already recorded as strings so that the serialiser can be
    applied uniformly to every datetime-shaped field on a row.
    """
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = try_parse(dt)
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def default_iso():
    return iso(now())


def parse(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    else:
        raise ValueError("unparseable datetime: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def try_parse(value):
    """Parse a client-supplied datetime, returning None when it is unusable."""
    try:
        return parse(value)
    except Exception:
        return None


_CURRENT = [parse(DEFAULT_CURRENT_UTC)]