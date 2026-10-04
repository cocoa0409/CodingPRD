"""In-memory data store.

The store is process-local and starts empty on every boot: nothing is seeded,
preloaded or hardcoded.  Every entity in the system is created by a client
through one of the declared endpoints.
"""

import uuid
from datetime import datetime, timezone

from util import fmt_iso

# The logical clock's startup default is exactly 2026-09-01T00:00:00Z and the
# server must never fall back to real wall-clock time before the first advance.
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

PROJECTS = {}
BID_ITEMS = {}
SURETIES = {}
COMMITMENTS = {}
BONDS = {}
QUOTES = {}
MEASUREMENTS = {}
RECONCILIATIONS = {}
CONDITIONS = {}
DETERMINATIONS = {}

_COLLECTIONS = {
    "project": PROJECTS,
    "bid_item": BID_ITEMS,
    "surety": SURETIES,
    "commitment": COMMITMENTS,
    "bond": BONDS,
    "quote": QUOTES,
    "measurement": MEASUREMENTS,
    "reconciliation": RECONCILIATIONS,
    "condition": CONDITIONS,
    "determination": DETERMINATIONS,
}

_state = {"clock": DEFAULT_CLOCK, "seq": 0}


def clock():
    return _state["clock"]


def set_clock(moment):
    _state["clock"] = moment


def new_id():
    return str(uuid.uuid4())


def _next_seq():
    _state["seq"] += 1
    return _state["seq"]


def create(kind, fields):
    """Create a record carrying the common fields plus the supplied fields."""
    now = clock()
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    record.update(fields)
    _COLLECTIONS[kind][record["id"]] = record
    return record


def touch(record):
    """Mark a resource as mutated: refresh updated_at and bump version by one."""
    record["updated_at"] = clock()
    record["version"] = record.get("version", 1) + 1
    return record


def refresh(record):
    """Recompute derived values on a read without advancing the version."""
    return record


def all_of(kind):
    return list(_COLLECTIONS[kind].values())


def ordered(kind, records=None):
    """Creation-timestamp ascending; ties broken by insertion order."""
    items = records if records is not None else all_of(kind)
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def public(record):
    """Serialise a record for a response, dropping internal bookkeeping."""
    out = {}
    for key, value in record.items():
        if key.startswith("_") and key != "_seq":
            continue
        if key == "_seq":
            continue
        out[key] = fmt_iso(value) if isinstance(value, datetime) else value
    return out


def find(kind, record_id):
    return _COLLECTIONS[kind].get(record_id)


def reset():
    """Test/utility helper — clears every collection and the logical clock."""
    for collection in _COLLECTIONS.values():
        collection.clear()
    _state["clock"] = DEFAULT_CLOCK
    _state["seq"] = 0
