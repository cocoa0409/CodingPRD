"""In-memory data store. Pure Python dicts keyed by id; no disk, no seeding.

Every boot starts empty. Records are plain dicts. Common fields (per PRD 2.5):
id, created_at, updated_at, version (starts at 1, +1 on every mutation) and an
internal monotonic insertion sequence `_seq` used as the deterministic
tie-break wherever created_at values tie (logical clock not moved between
creations). TemperatureReadings carry only id/created_at (PRD 2.5 exception).
"""
import uuid

import clock

DB = {
    "sites": {},
    "products": {},
    "trains": {},
    "campaigns": {},
    "seed_stages": {},
    "batches": {},
    "tests": {},
    "deviations": {},
    "shipments": {},
    "readings": {},
    "studies": {},
    "inspections": {},
    "materials": {},
}

_SEQ = {"n": 0}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def create_rec(kind, fields, common=True):
    """Insert a new record of `kind` with system-managed common fields."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["_seq"] = next_seq()
    rec["created_at"] = clock.now()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    DB[kind][rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and bump version (PRD 2.5: every mutation)."""
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 1) + 1


def get(kind, rec_id):
    return DB[kind].get(rec_id)


def all_recs(kind):
    return list(DB[kind].values())


def sort_created(recs):
    """Default list order: created_at ascending, insertion seq as tie-break."""
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))
