"""In-memory data store.

Python dicts only.  No SQLite, no JSON on disk, no /tmp cache.  The store is
constructed empty on every process boot: nothing here is seeded, preloaded,
registered or hardcoded.  Every entity a test needs is built through the
declared API surface.
"""

import datetime
import uuid

from constants import DEFAULT_CLOCK, parse_dt

# Entity collection keys.  One dict per entity, keyed by id.
COLLECTIONS = (
    "licenses",
    "product_lines",
    "card_sets",
    "pack_configurations",
    "signing_sessions",
    "artwork_approvals",
    "print_run_decisions",
    "redemptions",
    "collector_notifications",
    "distribution_allocations",
    "quality_claims",
    "collector_complaints",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        # Insertion order per collection, used as the creation-timestamp tie
        # break so an ascending created_at sort is deterministic.
        self.order = {name: [] for name in COLLECTIONS}
        self.clock = parse_dt(DEFAULT_CLOCK)

    # -- id / collection helpers -------------------------------------------
    def new_id(self):
        """A server-minted UUID carrying no type prefix."""
        return str(uuid.uuid4())

    def insert(self, collection, record):
        getattr(self, collection)[record["id"]] = record
        self.order[collection].append(record["id"])

    def all(self, collection):
        """Every record of a collection in creation order."""
        bucket = getattr(self, collection)
        return [bucket[i] for i in self.order[collection] if i in bucket]

    def get(self, collection, entity_id):
        return getattr(self, collection).get(entity_id)

    def exists(self, collection, entity_id):
        return entity_id in getattr(self, collection)

    # -- clock --------------------------------------------------------------
    def now(self):
        return self.clock


STORE = Store()


def reset_store():
    """Rebuild the store empty.  Used by the test-driving reset path only."""
    global STORE
    STORE = Store()
    return STORE


def record(collection, fields, now):
    """Build a base record with the four common properties of PRD 2.5."""
    rec = {
        "id": STORE.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    rec.update(fields)
    return rec


def touch(rec, now):
    """Refresh updated_at.  A derived/aggregate recompute is a field write
    (PRD 2.5) so it refreshes updated_at without bumping version."""
    rec["updated_at"] = now


def bump(rec, now):
    """A transition of the record's own state: version + updated_at."""
    rec["version"] = rec.get("version", 0) + 1
    rec["updated_at"] = now