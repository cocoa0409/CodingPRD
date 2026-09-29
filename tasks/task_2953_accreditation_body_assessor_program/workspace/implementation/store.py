"""In-memory store, logical clock, identity/audit helpers.

Storage is process-local Python dicts only. Nothing is seeded at import time or at
boot: every row is created by an API call.
"""

import threading
import uuid
from datetime import datetime, timedelta

LOCK = threading.RLock()

KINDS = (
    "schemes",
    "assessors",
    "qualifications",
    "declarations",
    "organizations",
    "applications",
    "assignments",
    "plans",
    "sessions",
    "nonconformities",
    "decisions",
    "scopes",
    "complaints",
)

DB = {kind: {} for kind in KINDS}

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0)
_STATE = {"clock": DEFAULT_CLOCK, "seq": 0}


# ---------------------------------------------------------------- logical clock
def clock_now():
    return _STATE["clock"]


def set_clock(value):
    _STATE["clock"] = value


def clock_date():
    return _STATE["clock"].date()


def iso_instant(value):
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)


def iso_date(value):
    return value.isoformat()


def now_iso():
    return iso_instant(clock_now())


def today_iso():
    return clock_date().isoformat()


def add_days(day, count):
    return day + timedelta(days=int(count))


# --------------------------------------------------------------------- identity
def new_id():
    return str(uuid.uuid4())


def next_seq():
    _STATE["seq"] += 1
    return _STATE["seq"]


def _touched_set():
    from flask import g

    if not hasattr(g, "touched"):
        g.touched = set()
    return g.touched


def touch(record):
    """Bump version/updated_at at most once per record per request."""
    seen = _touched_set()
    key = (record.get("_kind"), record["id"])
    if key in seen:
        return record
    seen.add(key)
    if "version" in record:
        record["version"] = record["version"] + 1
    if "updated_at" in record:
        record["updated_at"] = now_iso()
    return record


def set_fields(record, **fields):
    """Apply cascade fields; bump the record only when something really changed."""
    changed = any(record.get(key) != value for key, value in fields.items())
    record.update(fields)
    if changed:
        touch(record)
    return changed


def insert(kind, fields, audited=True):
    record = {"id": new_id()}
    record.update(fields)
    record["created_at"] = now_iso()
    if audited:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    record["_kind"] = kind
    record["_seq"] = next_seq()
    DB[kind][record["id"]] = record
    # A freshly created row must never be bumped again by the same request.
    _touched_set().add((kind, record["id"]))
    return record


def public(record):
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        if isinstance(value, list):
            out[key] = [dict(v) if isinstance(v, dict) else v for v in value]
        elif isinstance(value, dict):
            out[key] = dict(value)
        else:
            out[key] = value
    return out


def rows(kind):
    return list(DB[kind].values())


def get(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[kind].get(row_id)


def ordered(records):
    """Default collection order: created_at ascending, insertion order as tiebreak."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def newest(records):
    if not records:
        return None
    return max(records, key=lambda r: (r["created_at"], r["_seq"]))
