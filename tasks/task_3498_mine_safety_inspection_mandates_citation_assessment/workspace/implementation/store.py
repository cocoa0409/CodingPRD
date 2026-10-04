"""In-memory entity store.

Plain dicts keyed by id. The store starts EMPTY on every boot: nothing here
seeds, preloads, or hardcodes entity data; every entity enters through an API
call. Per-test-server isolation restarts the process, so module-level dicts are
naturally reset for every test.

Every entity carries the uniform system-managed properties of PRD section 2.4:
id (dashed UUID), created_at, updated_at, version (starts at 1 and increments
by exactly one on every mutation). A hidden _seq insertion counter provides a
deterministic tiebreak for created_at-ascending list ordering.
"""
import uuid

import clock

operators = {}
mines = {}
inspectors = {}
cycles = {}
inspections = {}
citations = {}
assessments = {}
idos = {}
contests = {}
plans = {}
accidents = {}
screenings = {}

_seq = {"n": 0}


def _next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_entity(collection, fields):
    """Create and store an entity dict with system-managed properties."""
    entity = dict(fields)
    entity["id"] = str(uuid.uuid4())
    stamp = clock.now()
    entity["created_at"] = stamp
    entity["updated_at"] = stamp
    entity["version"] = 1
    entity["_seq"] = _next_seq()
    collection[entity["id"]] = entity
    return entity


def touch(entity):
    """Record a mutation: version += 1 and updated_at refreshed (PRD 2.4)."""
    entity["version"] += 1
    entity["updated_at"] = clock.now()
