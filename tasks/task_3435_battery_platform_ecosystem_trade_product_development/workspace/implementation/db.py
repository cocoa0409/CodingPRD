"""In-memory data store and the logical platform clock.

Storage is process-local dicts keyed by id. Nothing is seeded at startup:
every entity is created through the declared API surface. Re-invoking
start.sh (fresh process) wipes all state, as required by the per-test-server
isolation contract.
"""
import itertools
import uuid
from datetime import datetime, timezone

# id -> entity dict, one collection per entity type (flat topology).
STORE = {
    "platforms": {},
    "packs": {},
    "chargers": {},
    "tools": {},
    "insights": {},
    "centers": {},
    "accounts": {},
    "assets": {},
    "claims": {},
    "partners": {},
    "listings": {},
    "cases": {},
    "bulletins": {},
}

# Monotonic insertion sequence; used as a deterministic tie-breaker whenever
# created_at values coincide (the logical clock only moves when set).
_SEQ = itertools.count(1)

# The logical platform clock. Startup default is exactly 2026-09-01T00:00:00Z
# and it never falls back to wall-clock time (PRD 2.5).
_CLOCK = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}


def next_seq():
    return next(_SEQ)


def new_id():
    return str(uuid.uuid4())


def clock_now():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt
