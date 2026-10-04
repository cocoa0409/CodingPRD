"""In-memory data store and the program logical clock.

Storage is Python dicts keyed by id only — no SQLite, no files, no /tmp cache.
A module-level singleton is used, so a fresh process start (start.sh
re-invocation under per-test-server isolation) wipes all state. Nothing is
seeded or preloaded: the store starts empty and every entity is constructed
via the declared API surface.

The logical clock starts at exactly 2026-09-01T00:00:00Z (PRD 2.5) and is
administered only through POST /_clock/set_current_utc. The server never
consults wall-clock time.
"""
import uuid
from datetime import datetime, timezone

from constants import DEFAULT_CLOCK_STR


def _default_clock():
    dt = datetime.fromisoformat(DEFAULT_CLOCK_STR.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc)


class Store(object):
    def __init__(self):
        self.clock = _default_clock()
        # Monotonic creation sequence: stable tie-break for created_at ordering
        # (the logical clock can sit still across many creates).
        self.seq = 0
        self.collections = {}
        self.batches = {}
        self.lots = {}
        self.sites = {}
        self.zones = {}
        self.orders = {}
        self.takebacks = {}
        self.reports = {}
        self.claims = {}
        self.offsets = {}
        self.targets = {}
        self.packages = {}

    def now(self):
        return self.clock

    def next_seq(self):
        self.seq += 1
        return self.seq


STORE = Store()


def new_common(store):
    """Common system-managed fields (PRD 2.4): id/created_at/updated_at/version."""
    ts = store.now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(store, ent):
    """Every mutation of an entity's own stored fields — direct, cascaded, or
    automatic — bumps updated_at and increments version by exactly 1 (PRD 2.4).
    One client-visible operation bumps an affected entity once."""
    ent["updated_at"] = store.now()
    ent["version"] += 1
