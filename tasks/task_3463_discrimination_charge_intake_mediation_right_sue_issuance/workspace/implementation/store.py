"""In-memory data store.

The store starts empty on every boot (the harness re-launches the server per
test). No entity is seeded, preloaded, or hardcoded; every row is created
through the declared API surface. The logical clock boots to the pinned
default and never reads the wall clock.
"""

import threading
from datetime import datetime, timezone


def _boot_clock():
    return datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        # Entity tables: dict keyed by id, insertion-ordered.
        self.complainants = {}
        self.employers = {}
        self.deferral_agencies = {}
        self.charges = {}
        self.mediation_cases = {}
        self.mediation_sessions = {}
        self.investigation_cases = {}
        self.evidence_requests = {}
        self.witness_interviews = {}
        self.determinations = {}
        self.conciliation_processes = {}
        self.remedy_packages = {}
        self.right_to_sue_notices = {}
        self.systemic_cases = {}
        self.disclosure_records = {}

        # The single logical clock (PRD section 2.4). Boots to the pinned
        # default regardless of wall-clock time.
        self.clock = _boot_clock()

        # Monotonic insertion counter, used as a stable tiebreaker when
        # sorting lists by created_at (several rows can share one logical
        # timestamp).
        self.seq = 0

        # Guards the store against interleaved requests when the dev server
        # runs threaded.
        self.lock = threading.RLock()

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()
