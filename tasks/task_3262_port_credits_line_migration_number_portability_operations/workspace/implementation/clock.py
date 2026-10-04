"""Logical clock and time arithmetic.

The API never reads wall-clock time. A single logical clock drives every temporal
decision and starts at exactly 2026-09-01T00:00:00Z (PRD 2.4). A "billing cycle"
is 30 days (PRD 3.5).
"""

from datetime import datetime, timedelta, timezone

CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
DAYS_PER_BILLING_CYCLE = 30

_state = {"now": None}


def now():
    """Current logical clock instant."""
    if _state["now"] is None:
        _state["now"] = parse_instant(CLOCK_DEFAULT)
    return _state["now"]


def set_now(instant):
    _state["now"] = instant


def parse_instant(value):
    """Parse an ISO 8601 instant (Z suffix or explicit offset) into aware UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt(dt):
    """ISO 8601 UTC timestamp with three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = parse_instant(dt)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_now():
    return fmt(now())


def to_iso(value, field="instant"):
    """Parse a client-supplied instant, refusing anything unparseable."""
    try:
        return parse_instant(value)
    except (ValueError, TypeError):
        return None


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def days_between(earlier, later):
    return (later - earlier).total_seconds() / 86400.0


def months_between(earlier, later):
    """Whole months between two instants, using 30-day months floored."""
    if earlier is None or later is None or later < earlier:
        return 0
    return int(days_between(earlier, later) // 30)


def completed_cycles(earlier, later):
    """Completed monthly billing cycles since an instant; partials discarded."""
    if earlier is None or later is None or later < earlier:
        return 0
    return int(days_between(earlier, later) // DAYS_PER_BILLING_CYCLE)


def day_of_month(dt):
    return dt.day