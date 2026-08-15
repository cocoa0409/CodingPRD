"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No entity is seeded at startup: every record is created through the declared API.
"""
import itertools

from clock import CLOCK
from util import new_id

COLLECTIONS = [
    "homeowners",
    "homes",
    "service_requests",
    "work_orders",
    "trade_partners",
    "chargebacks",
    "warranty_reserves",
    "reserve_entries",
    "administrator_claims",
]

db = {name: {} for name in COLLECTIONS}

_seq = itertools.count(1)


def next_seq() -> int:
    return next(_seq)


def new_entity() -> dict:
    """Common system-managed properties (PRD 2.5): id, created_at, updated_at, version."""
    now = CLOCK.now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def sorted_items(collection: str):
    """List order: created_at ascending, insertion order as tie-break (PRD 2.3)."""
    return sorted(db[collection].values(), key=lambda e: (e["created_at"], e["_seq"]))
