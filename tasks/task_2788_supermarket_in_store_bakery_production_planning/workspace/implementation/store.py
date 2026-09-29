"""In-memory data store.

Every collection is a plain dict keyed by entity id.  The store is empty on
every boot: no entity is ever seeded, preloaded or hardcoded here -- tests
construct all state through the declared endpoints.
"""

import copy
import datetime

from util import UTC, new_uuid, now_wall

COLLECTIONS = (
    "departments",
    "bake_days",
    "ovens",
    "products",
    "ingredients",
    "runs",
    "pickup_slots",
    "cake_orders",
    "ingredient_orders",
    "waste_records",
)

# PRD 2.11 -- the logical clock's startup value.
CLOCK_EPOCH = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = 0
        self._snapshot = None

    # -- logical clock ----------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, instant):
        self.clock = instant

    # -- sequencing -------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- atomicity --------------------------------------------------------
    def snapshot(self):
        self._snapshot = (
            {name: copy.deepcopy(getattr(self, name)) for name in COLLECTIONS},
            self.clock,
            self._seq,
        )

    def rollback(self):
        if self._snapshot is None:
            return
        data, clock, seq = self._snapshot
        for name in COLLECTIONS:
            setattr(self, name, data[name])
        self.clock = clock
        self._seq = seq
        self._snapshot = None

    def commit(self):
        self._snapshot = None


db = Store()


def new_entity(**fields):
    """Mint a row with the four common system-managed properties (PRD 2.4)."""
    stamp = now_wall()
    row = {
        "id": new_uuid(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    return row


def by_seq(rows):
    """created_at ascending == insertion order (stable list ordering)."""
    return sorted(rows, key=lambda row: row["_seq"])
