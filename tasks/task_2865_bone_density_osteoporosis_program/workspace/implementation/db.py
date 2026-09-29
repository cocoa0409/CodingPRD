"""In-memory store and the logical clock (PRD 2.4).

Nothing is ever seeded here: every collection starts empty on every boot and
all entities are created through the declared endpoints.
"""
import itertools
import uuid
from datetime import datetime, timezone

from util import fmt_instant

INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "payer_policies",
    "densitometers",
    "qc_runs",
    "calibration_events",
    "patients",
    "risk_factor_profiles",
    "scan_orders",
    "scan_appointments",
    "scan_sessions",
    "site_measurements",
    "positioning_reviews",
    "frax_assessments",
    "diagnostic_reports",
    "treatment_plans",
    "adherence_refills",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = INITIAL_CLOCK
        self._counter = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._counter)


db = Store()


def now():
    return db.clock


def now_iso():
    return fmt_instant(db.clock)


def today():
    return db.clock.date()


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    record = {"id": new_id(), "created_at": now_iso(), "_seq": db.next_seq()}
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """A mutation: refresh updated_at and increment version where present."""
    if "version" in record:
        record["updated_at"] = now_iso()
        record["version"] = record["version"] + 1
    return record


def public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def by_created_asc(record):
    return (record["created_at"], record["_seq"])


def rows(collection):
    return list(collection.values())
