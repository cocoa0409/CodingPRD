"""In-memory data store (PRD §2.5).

Plain dicts keyed by id; the process starts empty on every boot. Each record is
a dict carrying the four common fields (id, created_at, updated_at, version)
plus a hidden `_seq` used as the monotonic creation-order key for list sorting
and waitlist ranking (created_at ASC, never id).
"""

import itertools
import uuid
from datetime import datetime, timezone

from util import fmt_dt

TABLE_NAMES = [
    "programs",
    "classrooms",
    "families",
    "children",
    "registrations",
    "volunteers",
    "screening_checks",
    "role_assignments",
    "accommodation_plans",
    "supply_orders",
    "supply_items",
    "supply_distributions",
    "program_days",
    "security_tags",
    "attendance_records",
    "family_messages",
    "retention_entries",
]

db = {name: {} for name in TABLE_NAMES}

_seq_counter = itertools.count(1)
_last_ms = 0


def _now_iso_monotonic():
    """Wall-clock UTC timestamp, forced strictly monotonic across creations."""
    global _last_ms
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if now_ms <= _last_ms:
        now_ms = _last_ms + 1
    _last_ms = now_ms
    dt = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc)
    return fmt_dt(dt)


def new_record(**fields):
    """Create a record dict with the common system fields populated."""
    ts = _now_iso_monotonic()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq_counter),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Register a mutation: version += 1 and updated_at refreshed."""
    rec["version"] += 1
    rec["updated_at"] = _now_iso_monotonic()


def put(table, rec):
    db[table][rec["id"]] = rec
    return rec


def get(table, rec_id):
    if rec_id is None:
        return None
    return db[table].get(rec_id)


def all_of(table):
    return db[table].values()


def delete(table, rec_id):
    db[table].pop(rec_id, None)


def by_seq(records):
    """Sort by creation order (created_at ASC semantics via the monotonic seq)."""
    return sorted(records, key=lambda r: r["_seq"])


def strip_internal(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}
