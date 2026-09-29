"""In-memory store. Every collection starts empty on every boot: no seeding."""

import itertools
import uuid
from datetime import datetime, timezone

# PRD section 2.5: until an operator moves it, the clock reads 2026-08-01T00:00:00Z.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "state_license_profiles",
    "sellers",
    "buyers",
    "route_listings",
    "service_accounts",
    "billing_history_records",
    "route_valuations",
    "deals",
    "escrow_accounts",
    "license_transfers",
    "attrition_events",
    "clawback_settlements",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


def wall_now():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def new_record(ledger=False):
    """A fresh record. Ledger rows (BillingHistoryRecord, AttritionEvent) carry
    only id and created_at -- no updated_at and no version (PRD section 2.4)."""
    ts = wall_now()
    rec = {"id": new_id(), "created_at": ts, "_seq": store.next_seq()}
    if not ledger:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version by exactly 1."""
    rec["updated_at"] = wall_now()
    rec["version"] = rec.get("version", 1) + 1


def ordered(collection, predicate=None):
    rows = [r for r in collection.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
