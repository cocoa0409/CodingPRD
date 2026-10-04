"""In-memory data store. Pure Python dicts keyed by id; no disk, no SQLite.

Every byte of state vanishes when start.sh re-launches (per-test-server
isolation). Nothing is seeded at startup: all state arrives via API calls.
"""

import uuid

from flask import g

import clock

store = {
    "accident_cases": {},
    "investigations": {},
    "party_organizations": {},
    "party_designations": {},
    "groups": {},
    "recorders": {},
    "safety_recommendations": {},
    "board_meetings": {},
}

_seq = {"value": 0}


def new_id():
    return str(uuid.uuid4())


def add(kind, fields):
    """Mint and store a top-level entity with the section-2.5 common fields."""
    _seq["value"] += 1
    entity = dict(fields)
    entity["id"] = new_id()
    now = clock.wall_now_iso()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = _seq["value"]
    store[kind][entity["id"]] = entity
    return entity


def all_of(kind):
    """All entities of a collection in creation order (list sort, section 2.3)."""
    return sorted(store[kind].values(), key=lambda entity: entity["_seq"])


def touch(entity):
    """Bump version and refresh updated_at — at most once per request.

    PRD 2.5/2.10: every resource mutated by an operation (primary or cascade)
    gets its own version increment and updated_at refresh; a resource mutated
    twice along one cascade still increments by exactly one.
    """
    touched = getattr(g, "_touched_entities", None)
    if touched is None:
        touched = set()
        g._touched_entities = touched
    key = id(entity)
    if key in touched:
        return
    touched.add(key)
    entity["version"] = int(entity.get("version", 0)) + 1
    entity["updated_at"] = clock.wall_now_iso()
