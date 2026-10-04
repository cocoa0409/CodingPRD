"""In-memory data store and the program logical clock.

Storage is plain Python dicts only. The store starts EMPTY on every boot:
no seeding, no preloading, no hardcoded entities. Every entity is created
through the declared API surface.
"""
import threading
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # The logical clock. Before any coordinator sets it, it reads exactly
        # 2026-09-01T00:00:00Z and never falls back to wall-clock time.
        self.clock = DEFAULT_CLOCK
        self.seq = 0  # internal monotonic insertion sequence (never exposed)
        self.members = {}
        self.employers = {}
        self.ombudsmen = {}
        self.service_periods = {}
        self.cases = {}
        self.rounds = {}
        self.notes = {}
        self.analyses = {}
        self.assessments = {}
        self.referrals = {}
        self.statements = {}
        self.awards = {}
        self.events = {}
        self.training_records = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()
