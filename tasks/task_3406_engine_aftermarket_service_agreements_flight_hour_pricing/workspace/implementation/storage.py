"""In-memory storage and the logical clock.

The store starts EMPTY on every boot: no seeding, no preloading. Every entity
is created through the declared API surface. Datetimes are stored internally as
timezone-aware UTC datetime objects; serializers render them.
"""
import itertools
import uuid
from datetime import datetime, timezone

DB = {
    "operators": {},
    "engines": {},
    "agreements": {},
    "reports": {},
    "statements": {},
    "visits": {},
    "workscopes": {},
    "requisitions": {},
    "spares": {},
    "leases": {},
    "directives": {},
    "snapshots": {},
}

# Monotonic insertion counter, used as a deterministic sort tie-break.
_seq = itertools.count(1)

# PRD 2.4: before any client call the logical clock reads exactly this instant
# and never falls back to wall-clock time.
_INITIAL_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = _INITIAL_CLOCK


def now():
    """Current logical-clock reading (aware UTC datetime)."""
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def touch(entity):
    """PRD 2.5: version increments by 1 with every modification, updated_at
    refreshes. Timestamps follow the logical clock."""
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 1) + 1
