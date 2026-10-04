"""In-memory data store.

Nothing is seeded here. Every entity is created by a caller through the
declared API surface; the store starts empty on every boot.
"""

import threading
import uuid
from datetime import datetime, timezone

import timeutil

# ---------------------------------------------------------------------------
# In-memory tables — Python dicts keyed by id, no external persistence.
# ---------------------------------------------------------------------------

TABLES = [
    "franchisees",
    "stores",
    "agreements",
    "settlements",
    "revenue_lines",
    "draws",
    "rebates",
    "shrink_audits",
    "delivery_windows",
    "fresh_orders",
]

DB = {name: {} for name in TABLES}

# Insertion order per table, used for the draw waterfall's final tie-break and
# for stable list ordering.
INSERTION_ORDER = {name: [] for name in TABLES}

# Configurable percentage amendments are snapshotted per calculation rather
# than globally, so nothing else is cached here.

_clock = {"current_utc": timeutil.parse_utc(timeutil.DEFAULT_CLOCK)}

# Every mutation re-enters through a single guard so a cascade cannot
# interleave with a concurrent request.
LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def clock():
    return _clock["current_utc"]


def set_clock(value):
    _clock["current_utc"] = timeutil.required_utc(value)


def now():
    """Server timestamp for created_at / updated_at.

    Uses wall-clock time so identifiers and timestamps are always well formed,
    but every temporal business rule reads the logical clock instead.
    """
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def insert(table, record):
    record.setdefault("id", new_id())
    record.setdefault("created_at", now())
    record.setdefault("version", 1)
    record["updated_at"] = record["created_at"]
    DB[table][record["id"]] = record
    INSERTION_ORDER[table].append(record["id"])
    return record


def get(table, record_id):
    return DB[table].get(record_id)


def touch(record):
    """Any derived or computed field recompute is a mutation (PRD §2.5)."""
    record["updated_at"] = now()
    record["version"] = record.get("version", 1) + 1
    return record


def all_of(table):
    return [DB[table][i] for i in INSERTION_ORDER[table] if i in DB[table]]


def find(table, **criteria):
    out = []
    for record in all_of(table):
        if all(record.get(k) == v for k, v in criteria.items()):
            out.append(record)
    return out


def find_one(table, **criteria):
    for record in all_of(table):
        if all(record.get(k) == v for k, v in criteria.items()):
            return record
    return None


def reset():
    """Only used by tests that import the module directly; never at startup."""
    for name in TABLES:
        DB[name].clear()
        INSERTION_ORDER[name].clear()
    _clock["current_utc"] = timeutil.parse_utc(timeutil.DEFAULT_CLOCK)