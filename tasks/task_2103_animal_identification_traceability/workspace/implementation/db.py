"""In-memory data store and the programme logical clock (PRD 2.4).

Storage is in-memory only (plain dicts keyed by id). The store starts empty on
every boot: nothing is seeded, preloaded, or hardcoded at startup. Every entity
a test needs is built through the declared API surface.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# PRD 2.4: before any client sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z, and it never falls back to real wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)
        self.producers = {}
        self.premises = {}
        self.suppliers = {}
        self.tag_lots = {}
        self.tags = {}
        self.animals = {}
        self.sightings = {}
        self.movements = {}
        self.trace_requests = {}
        self.hold_orders = {}
        self.recon_runs = {}
        self.awards = {}

    def now(self):
        return self.clock

    def next_seq(self):
        return next(self._seq)


store = Store()


def new_id():
    return str(uuid.uuid4())


def base_record(common_fields=True):
    """id + created_at (+ updated_at/version unless the entity opts out).

    PRD 2.4: Sighting rows are the single exception - they carry only id and
    created_at, no updated_at and no version.
    """
    now = store.now()
    rec = {"id": new_id(), "created_at": now}
    if common_fields:
        rec["updated_at"] = now
        rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def touch(rec):
    """PRD 2.8: every record a mutation/cascade touches gets a refreshed
    updated_at and an incremented version, even for a derived counter."""
    rec["updated_at"] = store.now()
    rec["version"] = rec.get("version", 0) + 1


def sort_key(rec):
    """Default list ordering: created_at ASC, insertion order as the stable
    tie-break when several rows share one logical-clock instant."""
    return (rec["created_at"], rec["_seq"])
