"""In-memory data store.

Storage is process-local and deliberately ephemeral: plain dicts keyed by id.
Nothing is written to disk and nothing is seeded at import time or at boot —
the store starts empty and every entity is created through the declared API
surface.  Because ``prd-bench-local-run --isolation per-test-server`` relaunches
``start.sh`` before each individual test, this module is re-imported fresh and
the previous run's state cannot leak into the next one.
"""

import uuid

from timeutil import parse_iso
from constants import LOGICAL_CLOCK_START

# Canonical ordering of entity insertion, used to build ids deterministically
# enough for chronological sorting without relying on dict insertion order.
_COLLECTION_NAMES = (
    "homeowners",
    "properties",
    "qualifications",
    "bridge_programs",
    "interim_loans",
    "bridge_advances",
    "carrying_costs",
    "repair_advances",
    "backup_offers",
    "listings",
    "agents",
    "referrals",
    "coordination_tasks",
    "disbursements",
)


class Store:
    """Holds every entity collection plus the logical clock."""

    def __init__(self):
        for name in _COLLECTION_NAMES:
            setattr(self, name, {})
        self.logical_clock = parse_iso(LOGICAL_CLOCK_START)
        # Monotonic counter used only to disambiguate same-timestamp ordering.
        self.sequence = 0

    # -- identity ----------------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_sequence(self):
        self.sequence += 1
        return self.sequence

    # -- convenience -------------------------------------------------------
    def all(self, collection):
        return list(getattr(self, collection).values())

    def get(self, collection, entity_id):
        return getattr(self, collection).get(entity_id)

    def put(self, collection, record):
        getattr(self, collection)[record["id"]] = record
        return record

    def remove(self, collection, entity_id):
        getattr(self, collection).pop(entity_id, None)

    def by_field(self, collection, field, value):
        return [r for r in getattr(self, collection).values() if r.get(field) == value]

    def first_by_field(self, collection, field, value):
        for record in getattr(self, collection).values():
            if record.get(field) == value:
                return record
        return None

    # -- orderings ---------------------------------------------------------
    def sorted_by_created(self, records):
        """Canonical list order: creation timestamp ascending (PRD 2.3)."""
        return sorted(
            records,
            key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)),
        )

    def advance_by_created(self, records):
        """Advance events ordered by advanced_at asc, then creation time asc."""
        return sorted(
            records,
            key=lambda r: (r.get("advanced_at") or "", r.get("created_at") or "", r.get("_seq", 0)),
        )


# The process-wide store singleton.  It is created empty and never seeded.
db = Store()


def reset():
    """Clear every collection.  Used by tests that construct their own app."""
    global db
    db = Store()
    return db