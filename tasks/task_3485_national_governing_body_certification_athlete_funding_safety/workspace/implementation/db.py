"""In-memory data store. Module-level dicts; every process boot starts empty.

Version / updated_at discipline (PRD section 2.4): every resource carries
id / created_at / updated_at / version. version increments by exactly 1 on
every mutation, including cascade mutations. Within one HTTP request an
entity is bumped at most once even when several cascade hops touch it.
"""
import itertools
import uuid

import timeutil

STORES = (
    "governing_bodies",
    "certification_cycles",
    "complaints",
    "athletes",
    "results",
    "funding_agreements",
    "abuse_reports",
    "selection_procedures",
    "rosters",
    "appeals",
    "commercial_deals",
)

governing_bodies = {}
certification_cycles = {}
complaints = {}
athletes = {}
results = {}
funding_agreements = {}
abuse_reports = {}
selection_procedures = {}
rosters = {}
appeals = {}
commercial_deals = {}

_seq = itertools.count(1)

# Request-scoped set of entity keys already version-bumped this request.
_marked = set()


def reset_marks():
    _marked.clear()


def _key(store, entity_id):
    return (store, entity_id)


def next_seq():
    return next(_seq)


def mint_id():
    return str(uuid.uuid4())


def create(store, fields):
    """Insert a new entity with the four common system fields."""
    entity = dict(fields)
    entity["id"] = mint_id()
    now_iso = timeutil.wall_now_iso()
    entity["created_at"] = now_iso
    entity["updated_at"] = now_iso
    entity["version"] = 1
    entity["_seq"] = next_seq()
    store_map = globals()[store]
    store_map[entity["id"]] = entity
    return entity


def mark(store, entity):
    """Record a mutation of an existing entity: version +1, updated_at refresh.

    Idempotent within a single request (the first mark wins).
    """
    key = _key(store, entity["id"])
    if key in _marked:
        return
    _marked.add(key)
    entity["version"] += 1
    entity["updated_at"] = timeutil.wall_now_iso()


def get(store, entity_id):
    return globals()[store].get(entity_id)


def all_of(store):
    return globals()[store].values()


def sorted_created(entities):
    """Default list ordering: created_at ascending (PRD 2.3)."""
    return sorted(entities, key=lambda e: (e["created_at"], e["_seq"]))
