"""In-memory data store. The store starts empty on every boot — no seeding.

Every entity any caller needs is constructed via the declared API surface.
Storage is plain dicts keyed by resource id. The logical clock starts at
2026-09-01T00:00:00Z and advances only via POST /naic/_clock/set_current_utc.
"""

import uuid
from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.model_acts = {}
        self.exposure_drafts = {}
        self.ballots = {}
        self.states = {}
        self.adoptions = {}
        self.reviews = {}
        self.insurers = {}
        self.filings = {}
        self.rbc_reports = {}
        self.producers = {}
        self.licenses = {}
        self.calls = {}
        self.responses = {}
        self.standards = {}
        self.clock = CLOCK_DEFAULT
        self.seq = 0  # global insertion counter, stable tiebreak for created_at sorts

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def new_id():
    # Dashed UUID form; the undashed uuid4().hex fails UUID validation downstream.
    return str(uuid.uuid4())


def base_record():
    """Common fields per PRD 2.4: id, created_at, updated_at, version.

    created_at/updated_at read from the logical clock. version starts at 1.
    """
    now = store.clock
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(rec):
    """Mutation stamp: version += 1 and updated_at := current logical clock."""
    rec["version"] += 1
    rec["updated_at"] = store.clock


def state_by_code(code):
    for s in store.states.values():
        if s["code"] == code:
            return s
    return None
