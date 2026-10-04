# In-memory data store — plain dicts keyed by id. Starts empty on every boot;
# nothing is seeded. Per-test-server isolation reboots give a fresh process.
import uuid

import clock

TABLES = [
    "suppliers",
    "lots",
    "lines",
    "products",
    "labels",
    "runs",
    "programs",
    "batches",
    "forecasts",
    "writedowns",
]

db = {name: {} for name in TABLES}

_seq_counter = {"n": 0}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def make_entity(table, fields):
    """Create and register an entity with the four common system properties
    (PRD 2.5). created_at/updated_at read the logical clock, version starts at 1."""
    ent = dict(fields)
    ent["id"] = new_id()
    ent["created_at"] = clock.now_ms()
    ent["updated_at"] = ent["created_at"]
    ent["version"] = 1
    ent["_seq"] = next_seq()
    ent["_dt"] = {}
    ent["_dirty"] = False
    db[table][ent["id"]] = ent
    return ent


def mark(ent):
    """Mark an entity as modified in the current request; flushed once."""
    ent["_dirty"] = True


def flush_dirty():
    """Apply the modification stamp: every entity touched in this request gets
    exactly one version increment and an updated_at refresh (PRD 2.10)."""
    for table in TABLES:
        for ent in db[table].values():
            if ent.pop("_dirty", False):
                ent["version"] += 1
                ent["updated_at"] = clock.now_ms()


def public(ent):
    """Serialize: strip internal underscore-prefixed bookkeeping keys."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}
