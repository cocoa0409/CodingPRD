"""In-memory store.

Every table is a plain dict keyed by the server-minted uuid.  Nothing is ever
written to disk and no entity is ever seeded: the process starts completely
empty and the API is the only way data enters the system.
"""

import itertools
import uuid

from core import clock

_seq = itertools.count(1)

TABLE_NAMES = [
    "branches",
    "rooms",
    "programs",
    "reservations",
    "presenters",
    "contracts",
    "challenges",
    "tiers",
    "participants",
    "entries",
    "lots",
    "awards",
]

DB = dict((name, {}) for name in TABLE_NAMES)


def new_id():
    return str(uuid.uuid4())


def new_entity(table, fields, versioned=True):
    """Persist a new entity.  created_at/updated_at read the logical clock."""
    entity = dict(fields)
    entity["id"] = new_id()
    entity["created_at"] = clock.now()
    entity["_seq"] = next(_seq)
    if versioned:
        entity["version"] = 1
        entity["updated_at"] = entity["created_at"]
    DB[table][entity["id"]] = entity
    return entity


def order_key(entity):
    """created_at ascending, with the insertion sequence as the tie-breaker.

    Many entities share an instant because the logical clock only moves when a
    caller moves it, so the sequence number is what makes list ordering and the
    allocation waterfall deterministic.
    """
    return (entity["created_at"], entity["_seq"])


def get(table, entity_id):
    if not isinstance(entity_id, str):
        return None
    return DB[table].get(entity_id)


def all_of(table):
    return sorted(DB[table].values(), key=order_key)


def where(table, **filters):
    out = []
    for entity in DB[table].values():
        keep = True
        for key, value in filters.items():
            if entity.get(key) != value:
                keep = False
                break
        if keep:
            out.append(entity)
    out.sort(key=order_key)
    return out
