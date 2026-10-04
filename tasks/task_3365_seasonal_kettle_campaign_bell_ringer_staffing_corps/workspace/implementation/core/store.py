"""In-memory data store.

Storage is IN-MEMORY ONLY: python dicts keyed by id.  Nothing is seeded,
preloaded or hardcoded at startup — every entity is created through the API, so
a fresh boot produces a completely empty store (SKILL.md Step 2 / output
checklist).

PRD 2.5: `id`, `created_at`, `updated_at` and `version` are system-managed on
every top-level resource.  `version` starts at 1 and is incremented by one on
every subsequent mutation; a write that changes only a derived or computed
field still counts as a mutation.
"""
from datetime import datetime

from . import clock

TABLES = (
    "units",
    "campaigns",
    "host_sites",
    "kettle_locations",
    "bell_ringers",
    "shifts",
    "kettle_collections",
    "digital_givings",
    "assistance_programs",
    "assistance_applications",
    "corps_programs",
    "disaster_deployments",
    "reallocation_decisions",
)

db = {name: {} for name in TABLES}
_seq = {"n": 0}


def reset():
    for name in TABLES:
        db[name].clear()
    _seq["n"] = 0
    clock.reset()


def _next_seq():
    _seq["n"] += 1
    return _seq["n"]


def insert(table, record):
    record["id"] = clock.new_id()
    stamp = clock.now_iso()
    record["created_at"] = stamp
    record["updated_at"] = stamp
    record["version"] = 1
    record["_seq"] = _next_seq()
    db[table][record["id"]] = record
    return record


def touch(record):
    """Record a mutation: refresh updated_at and advance version by one."""
    record["updated_at"] = clock.now_iso()
    record["version"] = int(record.get("version", 1)) + 1
    return record


def find(table, row_id):
    if not row_id:
        return None
    return db[table].get(row_id)


def rows(table):
    return list(db[table].values())


def ordered(table, extra_key=None):
    """Creation order (created_at ASC), stable against millisecond ties."""
    out = sorted(db[table].values(), key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
    if extra_key is not None:
        out.sort(key=extra_key)
    return out


def public(record):
    """Strip internal bookkeeping fields before serialization."""
    if record is None:
        return None
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = clock.fmt(value)
        else:
            out[key] = value
    return out
