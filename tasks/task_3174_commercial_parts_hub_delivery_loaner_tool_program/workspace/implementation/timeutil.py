"""Time parsing and formatting helpers.

Two clocks exist in this service and they must not be confused:

  * the logical clock, which starts at the fixed instant 2026-09-01T00:00:00Z
    and only moves when a PlatformAdmin says so (PRD 3.9).  Every
    time-dependent business rule reads it.
  * the wall clock, which is what the response envelope timestamps and the
    created_at/updated_at audit spine are drawn from.

Audit timestamps are emitted with exactly three fractional digits and are
strictly increasing inside a process, so that the ordering rules that tie-break
on created_at (stop sequencing, replacement selection) are deterministic.
"""

from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

_last_issued = [None]


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            raise ValueError("not an ISO 8601 instant: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_stamp():
    """Strictly increasing audit timestamp (wall clock, millisecond grid)."""
    current = datetime.now(timezone.utc).replace(microsecond=0)
    current = current.replace(microsecond=(datetime.now(timezone.utc).microsecond // 1000) * 1000)
    previous = _last_issued[0]
    if previous is not None and current <= previous:
        current = previous + timedelta(milliseconds=1)
    _last_issued[0] = current
    return format_iso(current)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def midnight_of(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def at_hour(dt, hour):
    return dt.replace(hour=hour, minute=0, second=0, microsecond=0)


def days_between(later, earlier):
    """Whole days elapsed between two instants, truncated toward zero."""
    if later is None or earlier is None:
        return 0
    return int((later - earlier).total_seconds() // 86400)