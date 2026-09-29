"""In-memory data store, logical clock and per-request version bookkeeping.

The store is process-local and always starts completely empty: no entity is ever
seeded, preloaded or hardcoded at import time or at startup. Every record is
created by a client through the declared API surface.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from calc import iso

# The logical clock reads exactly this instant before it is ever set, and never
# falls back to real wall-clock time (PRD section 2.9).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

PRODUCT_TYPES = ("DETACHED", "COTTAGE", "TOWNHOME")
ROLES = (
    "DeveloperPrincipal",
    "EntitlementOfficer",
    "ConstructionManager",
    "LeasingAgent",
    "AssetManager",
    "PropertyManager",
    "Household",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.communities = {}
        self.phases = {}
        self.homesites = {}
        self.schedules = {}
        self.programs = {}
        self.households = {}
        self.leases = {}
        self.turn_orders = {}
        self.reviews = {}
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """The current logical clock instant."""
        return self.clock


store = Store()


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------- record helpers
def new_record(kind, fields):
    """Create a record with the system-owned common fields (PRD section 2.4)."""
    moment = store.now()
    record = {
        "id": new_id(),
        "_kind": kind,
        "_seq": store.next_seq(),
        "_created": moment,
        "created_at": iso(moment),
    }
    if kind != "AbsorptionReview":
        record["updated_at"] = iso(moment)
        record["version"] = 1
    record.update(fields)
    return record


def sort_key(record):
    """Deterministic created_at ascending ordering, stable on identical instants."""
    return (record["_created"], record["_seq"])


def ordered(records):
    return sorted(records, key=sort_key)


# ---------------------------------------------------------------- version bookkeeping
# Every mutation that changes a resource increments its version by exactly 1 and
# refreshes updated_at, including mutations that reach the resource indirectly as
# part of a cascade (PRD section 2.4). A record touched several times inside one
# request is still a single mutation, so it is bumped exactly once.
class UnitOfWork:
    def __init__(self):
        self.dirty = {}
        self.created = set()

    def mark_created(self, record):
        self.created.add((record["_kind"], record["id"]))

    def mark(self, record):
        key = (record["_kind"], record["id"])
        if key in self.created:
            return
        self.dirty[key] = record

    def commit(self):
        moment = iso(store.now())
        for record in self.dirty.values():
            if record["_kind"] == "AbsorptionReview":
                continue
            record["version"] = record.get("version", 1) + 1
            record["updated_at"] = moment
        self.dirty = {}


def unit():
    from flask import g
    if not hasattr(g, "unit_of_work"):
        g.unit_of_work = UnitOfWork()
    return g.unit_of_work


def mark(record):
    unit().mark(record)


def mark_created(record):
    unit().mark_created(record)


def commit():
    unit().commit()


def set_field(record, field, value):
    """Assign a field and record the change for the version bump."""
    if record.get(field) != value:
        record[field] = value
        mark(record)


def set_instant(record, field, moment):
    """Store an instant as an ISO string plus a shadow datetime for comparisons."""
    record["_" + field] = moment
    set_field(record, field, iso(moment) if moment is not None else None)
