"""In-memory store.  Plain dicts keyed by id, nothing persisted, nothing
seeded: the collections below start empty on every process boot and the test
harness rebuilds every precondition through the declared endpoints.
"""

import threading
import uuid

from clockcal import COLD_START_CLOCK

_COLLECTIONS = (
    "customers",
    "tariffs",
    "facilities",
    "rail_cars",
    "cycles",
    "notifications",
    "charges",
    "invoices",
    "claims",
    "disputes",
    "evidence",
    "agreements",
    "complaints",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        for name in _COLLECTIONS:
            setattr(self, name, {})
        # Logical clock (PRD §2.4): cold start value, moved only by
        # POST /demurrage/_clock/set_current_utc.
        self.clock = COLD_START_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        # A server-minted UUID with no type prefix of any kind (PRD §2.4).
        return str(uuid.uuid4())

    def now(self):
        return self.clock

    # -- ordered scans -----------------------------------------------------
    def ordered(self, collection):
        """Rows ordered by created_at ASC then id ASC (PRD §2.3)."""
        rows = list(getattr(self, collection).values())
        rows.sort(key=lambda r: (r["created_at"], r["id"]))
        return rows


db = Store()


def base_record(kind, versioned=True):
    """Common fields of PRD §2.4.  A car notification and a piece of dispute
    evidence are deliberately lighter: id + created_at only."""
    now = db.now()
    rec = {
        "id": db.new_id(),
        "created_at": now,
        "_kind": kind,
        "_seq": db.next_seq(),
    }
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at to the current logical clock and bump version by
    exactly 1 (PRD §2.9)."""
    rec["updated_at"] = db.now()
    rec["version"] = rec.get("version", 1) + 1
    return rec
