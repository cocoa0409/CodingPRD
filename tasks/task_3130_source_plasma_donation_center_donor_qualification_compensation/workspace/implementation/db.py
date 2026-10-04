"""In-memory data store and logical clock.

The store starts empty on every boot. No seeding of any kind.
"""
import threading
import uuid
from datetime import datetime, timedelta, timezone

_LOCK = threading.RLock()

# Logical clock: default instant before any client set call.
_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

DB = {
    "plasma_centers": {},
    "donors": {},
    "screening_visits": {},
    "screening_sub_records": {},
    "donation_visits": {},
    "adverse_reactions": {},
    "donation_units": {},
    "compensation_schedules": {},
    "compensation_payments": {},
    "deferral_registry_entries": {},
    "lookback_cases": {},
    "capacity_snapshots": {},
}


def lock():
    return _LOCK


def next_id():
    return str(uuid.uuid4())


def now():
    return _clock


def set_clock(new_dt):
    global _clock
    _clock = new_dt


def ts(dt=None):
    """Format a datetime as ISO 8601 UTC with three fractional digits, Z suffix."""
    if dt is None:
        dt = _clock
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None when the value is not a valid datetime string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD date. Returns a date object or None."""
    if not isinstance(value, str):
        return None
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return None
    try:
        y = int(value[0:4])
        m = int(value[5:7])
        d = int(value[8:10])
        return datetime(y, m, d).date()
    except (ValueError, TypeError):
        return None


def touch(entity):
    """Refresh updated_at and bump version on a mutation."""
    entity["updated_at"] = ts()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity):
    entity["created_at"] = ts()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    return entity
