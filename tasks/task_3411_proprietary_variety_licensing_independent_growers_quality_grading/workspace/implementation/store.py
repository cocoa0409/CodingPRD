"""In-memory store and logical clock. Every boot starts empty; no seeding ever."""
import uuid
from datetime import datetime, timezone

import constants

# Entity tables: id -> record dict
db = {
    "varieties": {},
    "growers": {},
    "agreements": {},
    "plant_lots": {},
    "plantings": {},
    "harvest_windows": {},
    "harvest_lots": {},
    "pool_periods": {},
    "settlement_statements": {},
    "recall_orders": {},
}

# The single logical clock (PRD 2.4). Starts exactly at the pinned instant.
_clock = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}
assert constants.CLOCK_START_ISO == "2026-09-01T00:00:00Z"


def clock_now():
    return _clock["now"]


def clock_set(dt):
    _clock["now"] = dt


def new_id():
    return str(uuid.uuid4())


def new_req_id():
    return "req_" + uuid.uuid4().hex[:20]


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_iso():
    return iso(datetime.now(timezone.utc))


def init_record(rec):
    """Stamp common system fields on a freshly built record."""
    now = clock_now()
    rec["id"] = new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on any modification (incl. cascades)."""
    rec["updated_at"] = clock_now()
    rec["version"] += 1
