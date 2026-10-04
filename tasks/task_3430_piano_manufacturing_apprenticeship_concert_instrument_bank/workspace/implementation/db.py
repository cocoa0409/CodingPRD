"""In-memory store, logical clock, id/timestamp helpers.

Fresh boot = empty state. The logical clock starts at exactly
2026-09-01T00:00:00Z and never reads wall-clock time for domain data.
"""
import math
import uuid
from datetime import datetime, timezone

CLOCK_START_ISO = "2026-09-01T00:00:00Z"

STORE = {
    "wood_batches": {},
    "build_orders": {},
    "stage_logs": {},
    "craftsmen": {},
    "apprentices": {},
    "endorsements": {},
    "instruments": {},
    "artists": {},
    "loans": {},
    "restorations": {},
}

SEQ = {"creation": 0, "instrument_serial": 0}
_clock = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def new_id():
    return str(uuid.uuid4())


def creation_seq():
    SEQ["creation"] += 1
    return SEQ["creation"]


def next_serial():
    SEQ["instrument_serial"] += 1
    return "PIN-%08d" % SEQ["instrument_serial"]


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5 common fields)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_clock(dt):
    """Logical-clock reading, serialized as the clock's own whole-second form
    (PRD 2.4: the startup value is exactly 2026-09-01T00:00:00Z)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value):
    """Parse an ISO 8601 string to an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_days_between(later, earlier):
    """Integer number of whole 86400-second days elapsed, rounded down."""
    return int(math.floor((later - earlier).total_seconds() / 86400.0))


def touch(entity):
    """Every mutation bumps version and refreshes updated_at (logical clock)."""
    entity["updated_at"] = clock_now()
    entity["version"] += 1


def new_entity():
    now = clock_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": creation_seq(),
    }
