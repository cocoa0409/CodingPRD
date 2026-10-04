"""In-memory data store.

Every collection is a plain dict keyed by the entity's server-minted id. The
store is constructed empty at import time and is never seeded, preloaded or
hydrated from disk — a fresh process always starts with no entities at all
(PRD §2; the harness reboots the server before every test).
"""
import uuid
from collections import OrderedDict

from .envelope import iso8601_now

COLLECTIONS = (
    "partners",
    "agreements",
    "programs",
    "accounts",
    "applications",
    "transactions",
    "promo_plans",
    "settlement_batches",
    "disputes",
    "benefit_postings",
    "scheduled_balances",
    "transfers",
    # per-account payment scheduling metadata: account_id -> due_date
    "payment_due",
)


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, OrderedDict())

    def reset(self):
        for name in COLLECTIONS:
            getattr(self, name).clear()


store = Store()


def uid() -> str:
    """Server-minted UUID with no type prefix or namespace segment (PRD §2.6)."""
    return str(uuid.uuid4())


def add(collection: str, entity: dict) -> dict:
    """Insert a new entity, stamping the common property set (PRD §2.6)."""
    now = iso8601_now()
    entity["id"] = uid()
    entity["created_at"] = entity.get("created_at", now)
    entity["updated_at"] = now
    entity["version"] = 1
    getattr(store, collection)[entity["id"]] = entity
    return entity


def touch(entity: dict) -> dict:
    """Refresh updated_at and bump version by one on any mutation (PRD §2.6)."""
    entity["updated_at"] = iso8601_now()
    entity["version"] = entity.get("version", 1) + 1
    return entity


def all_of(collection: str):
    return list(getattr(store, collection).values())


def find(collection: str, **filters):
    rows = []
    for entity in getattr(store, collection).values():
        if all(entity.get(k) == v for k, v in filters.items()):
            rows.append(entity)
    return rows