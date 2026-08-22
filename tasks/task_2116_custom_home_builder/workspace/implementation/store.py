"""In-memory data store and the logical jobsite clock (PRD 2.4).

The store is EMPTY on every boot.  Nothing is seeded, preloaded or hardcoded:
every row is created by callers through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4 - before the first repositioning call the logical clock reads exactly
# 2026-08-01T00:00:00.000Z and never falls back to real wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "clients",
    "lenders",
    "staff_members",
    "subcontractors",
    "projects",
    "allowance_items",
    "selections",
    "change_orders",
    "schedule_tasks",
    "cost_entries",
    "draw_requests",
    "lien_waivers",
    "defect_tickets",
    "photo_documents",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})


db = Store()


def now():
    return db.clock


def set_clock(value):
    db.clock = value


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db._seq)


def base_row():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def bump(row):
    """A mutation of a row: refresh updated_at and increment version (PRD 2.4)."""
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1


def touch_time(row):
    """Derived-field refresh that is not a versioned mutation of the row."""
    row["updated_at"] = now()


def ordered(rows):
    """Deterministic natural ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
