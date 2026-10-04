"""In-memory data store.

Storage is process-memory only: plain dicts keyed by id. Nothing is written to
disk, nothing is cached in /tmp, and the store starts empty on every boot — no
entity is seeded, preloaded, or hardcoded here or anywhere else. Every entity a
client sees was constructed through a declared endpoint.
"""

import uuid

from apptime import now


class Store:
    def __init__(self):
        # Collections, all keyed by the row's own id.
        self.requesters = {}
        self.workers = {}
        self.qualification_types = {}
        self.qualification_exams = {}
        self.exam_attempts = {}
        self.worker_qualifications = {}
        self.hits = {}
        self.assignments = {}
        self.deposits = {}
        self.payouts = {}
        self.reviews = {}

        # Per-worker ordinals used by Assignment.sequence and by the exam
        # attempt sequence (one counter each, both minted independently).
        self.worker_assign_seq = {}
        self.worker_exam_seq = {}
        # The qualification gate is a snapshot: the grant set consulted at
        # acceptance is frozen for the life of the assignment (only advisory
        # diagnostics use it; the gate itself is re-read from the register).
        self.assignment_gate_snapshot = {}
        # Admission-rate snapshot captured when a HIT first reaches full cap.
        self.hit_admission_rate = {}
        # HIT version counters live on the row itself; nothing global needed.

    def clear(self):
        self.__init__()


db = Store()


def new_id() -> str:
    """A server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def common_fields() -> dict:
    """The standard field set every entity except Review carries (PRD §2.5)."""
    ts = now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(row: dict) -> None:
    """Mark a row mutated: refresh updated_at and advance version together."""
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1