"""In-memory data store. A fresh process starts completely empty — no seeding."""
import itertools
import uuid
from datetime import datetime, timezone

store = {
    "districts": {},
    "school_years": {},
    "specs": {},
    "students": {},
    "courses": {},
    "sections": {},
    "enrollments": {},
    "attendance_events": {},
    "incidents": {},
    "extracts": {},
    "portal_accounts": {},
    "feeds": {},
    "rollover_runs": {},
    "roster_links": {},  # (section_id, enrollment_id) -> {"active": bool, "created_at": str, "_seq": int}
}

_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


# Logical clock: before any call it reads exactly 2026-09-01T00:00:00Z and it
# never falls back to wall-clock time on its own.
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": DEFAULT_CLOCK}


def get_clock():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stamp_new(entity):
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    """Refresh updated_at and bump the OCC version on every mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
    return entity
