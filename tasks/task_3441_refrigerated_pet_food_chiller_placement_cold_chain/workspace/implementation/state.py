"""In-memory data store, logical clock, and shared helpers.

Storage is module-level dicts only; start.sh re-invocation wipes everything.
No seeding: every dict starts empty. The logical clock boots at exactly
2026-09-01T00:00:00Z per PRD section 2.4 and never falls back to wall clock.
"""
import uuid as _uuid
from datetime import datetime, timezone

DB = {
    "stores": {},
    "evaluations": {},
    "agreements": {},
    "chillers": {},
    "placements": {},
    "readings": {},    # chiller_id -> [reading dict, ...] in arrival order
    "tickets": {},
    "shipments": {},
    "lots": {},
    "positions": {},
    "projects": {},
    "campaigns": {},
}

CLOCK = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}
_SEQ = {"n": 0}


def now():
    return CLOCK["now"]


def set_now(dt):
    CLOCK["now"] = dt


def new_id():
    return str(_uuid.uuid4())


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def base_entity():
    """Common system fields per PRD section 2.5 (id/created_at/updated_at/version)."""
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """Every mutation bumps version by exactly 1 and refreshes updated_at."""
    entity["updated_at"] = now()
    entity["version"] += 1


def parse_dt(s):
    """Parse an ISO 8601 timestamp string into an aware UTC datetime."""
    t = s.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Business datetime echo: plain seconds when whole, else 3-digit ms."""
    if dt is None:
        return None
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def fmt_dt_ms(dt):
    """created_at/updated_at and meta timestamps: always three fractional digits."""
    if dt is None:
        return None
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms
