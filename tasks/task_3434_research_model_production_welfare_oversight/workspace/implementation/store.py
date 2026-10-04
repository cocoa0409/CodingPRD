"""In-memory data store and the logical clock.

Storage is in-memory only (plain dicts keyed by id). Nothing is seeded or
preloaded: every entity is created through the API. The logical clock starts
at the PRD-mandated default instant and never falls back to wall-clock time.
"""
import uuid
from datetime import datetime, timezone

CLOCK_START = "2026-09-01T00:00:00Z"


def parse_dt(value):
    """Parse an ISO-8601 instant into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Serialize an aware datetime as ISO-8601 UTC with 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


db = {
    "facilities": {},
    "rooms": {},
    "strains": {},
    "colonies": {},
    "cohorts": {},
    "health_screens": {},
    "customers": {},
    "orders": {},
    "allocations": {},
    "shipments": {},
    "protocols": {},
    "inspections": {},
    "contracts": {},
}

_seq = {"n": 0}
_clock = {"now": parse_dt(CLOCK_START)}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Monotonic creation counter; tie-breaks created_at for list sorting."""
    _seq["n"] += 1
    return _seq["n"]


def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt


def touch(coll, entity_id):
    """Increment an entity's version exactly once per mutating request and
    refresh updated_at (global version rule: one request, one increment per
    touched entity, however many cascade hops fire). Entities declared without
    a version field (ModelStrain, HealthScreen, Allocation, WelfareInspection)
    are silently skipped."""
    from flask import g
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    key = (coll, entity_id)
    if key in touched:
        return
    touched.add(key)
    ent = db[coll].get(entity_id)
    if ent is None:
        return
    if "version" in ent:
        ent["version"] += 1
    if "updated_at" in ent:
        ent["updated_at"] = now()


def sort_key(ent):
    return (ent["created_at"], ent.get("_seq", 0))
