"""In-memory data store.

Plain dicts keyed by entity id. No SQLite, no disk persistence of any kind.
The store starts empty on every boot; nothing is seeded at startup. The test
harness restarts the process before every test, which resets all state.
"""
import uuid

import clock

cycles = {}
colleges = {}
students = {}
counselors = {}
partners = {}
referrals = {}
prep_programs = {}
applications = {}
ranking_entries = {}
matches = {}
aid_packages = {}
verifications = {}
outcomes = {}


def new_id():
    """Server-minted UUID with no type prefix (PRD section 2.5)."""
    return str(uuid.uuid4())


def create(table, fields, common=True):
    """Insert a new entity. Common fields: id, created_at, updated_at, version
    (version starts at 1). RankingEntry passes common=False: it carries only
    id and created_at because it is never mutated in place (PRD section 2.5).
    """
    now = clock.now()
    entity = {"id": new_id(), "created_at": now}
    if common:
        entity["updated_at"] = now
        entity["version"] = 1
    entity.update(fields)
    table[entity["id"]] = entity
    return entity


def touch(entity):
    """Every mutation of a resource increments version by exactly 1 and
    refreshes updated_at -- including server-side cascade mutations
    (PRD section 2.5)."""
    entity["version"] = entity.get("version", 0) + 1
    entity["updated_at"] = clock.now()
