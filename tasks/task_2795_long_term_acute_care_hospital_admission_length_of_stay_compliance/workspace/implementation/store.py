"""In-memory data store.

The store starts completely empty on every boot: no entity is seeded, preloaded
or hardcoded. Tests build every precondition through the declared API surface.
"""

import uuid

from clock import now

# Entities that are append-only and therefore carry only `id` and `created_at`
# (PRD 2.4): DrgRateEntry and IdtNote.
_APPEND_ONLY = ("drg_rates", "idt_notes")


class Store(object):
    def __init__(self):
        self.hospitals = {}
        self.periods = {}
        self.patients = {}
        self.physicians = {}
        self.criteria_sets = {}
        self.drg_rates = {}
        self.referrals = {}
        self.stays = {}
        self.weaning_plans = {}
        self.idt_notes = {}
        self.interruptions = {}
        self.determinations = {}
        self.reviews = {}
        self.queries = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_row(collection_name):
    """Create a fresh row with its common audit fields stamped from the logical clock."""
    stamp = now()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "_seq": db.next_seq(),
    }
    if collection_name not in _APPEND_ONLY:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and bump version by exactly 1 (PRD 2.4, 2.9)."""
    if row is None:
        return
    row["updated_at"] = now()
    if "version" in row:
        row["version"] = row["version"] + 1


def sorted_rows(rows):
    """Default list ordering: created_at ascending, insertion order breaking ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sorted_rows_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
