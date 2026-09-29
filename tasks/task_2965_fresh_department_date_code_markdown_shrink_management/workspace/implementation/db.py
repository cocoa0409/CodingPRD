"""In-memory data store and the logical clock.

Nothing is seeded here: every collection starts empty on every boot and every
entity is created by an API call.  The logical clock starts at exactly
2026-08-01T00:00:00Z and NEVER falls back to host wall-clock time.
"""
import threading
import uuid
from datetime import datetime

from util import UTC

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "stores", "partners", "ladders", "departments", "items", "lots", "labels",
    "checks", "pickups", "assignments", "shrink_events", "audits", "findings",
    "recommendations",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def sort_key(record):
    """Deterministic created_at ASC ordering with an insertion-order tie-break.

    created_at is written from the logical clock, so many rows can share the
    same instant; the insertion sequence keeps the order stable and matches
    the "created_at ASC" ordering the PRD asks for everywhere.
    """
    return (record.get("created_at") or "", record.get("_seq") or 0)


def ordered(records):
    return sorted(records, key=sort_key)


def newest_first(records):
    return sorted(records, key=sort_key, reverse=True)
