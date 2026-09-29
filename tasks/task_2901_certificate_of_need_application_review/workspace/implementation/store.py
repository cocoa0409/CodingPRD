"""In-memory data store. Starts completely empty on every boot: no seeding."""

import uuid
from itertools import count

import clock

COLLECTIONS = (
    "health_service_areas",
    "state_plan_formulas",
    "hearing_rooms",
    "applicants",
    "letters_of_intent",
    "batching_cycles",
    "applications",
    "completeness_reviews",
    "public_comments",
    "interventions",
    "public_hearings",
    "score_sheets",
    "certificates",
    "progress_reports",
    "appeals",
)


class Store:
    def __init__(self):
        self._seq = count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def create(collection, fields, common=True):
    """Insert a record. `common` False means the PublicComment shape (id/created_at only)."""
    record = {"id": new_id()}
    record.update(fields)
    stamp = clock.now_str()
    record["created_at"] = stamp
    if common:
        record["updated_at"] = stamp
        record["version"] = 1
    record["_seq"] = db.next_seq()
    getattr(db, collection)[record["id"]] = record
    return record


def touch(record):
    """Register a mutation: refresh updated_at and increase version by exactly 1."""
    record["updated_at"] = clock.now_str()
    record["version"] = record.get("version", 0) + 1
    return record


def rows(collection):
    return list(getattr(db, collection).values())


def sort_created(records):
    """Default ordering: created_at ascending, insertion order as stable tie-break."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def get(collection, record_id):
    if not isinstance(record_id, str):
        return None
    return getattr(db, collection).get(record_id)
