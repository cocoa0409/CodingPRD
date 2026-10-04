"""In-memory store. Empty at every boot — no seeding.

The store is a plain module-level dict of dicts keyed by id. The logical
clock starts at 2026-09-01T00:00:00Z per PRD §2.6.
"""

from datetime import datetime, timezone

CLOCK_INITIAL = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.plans = {}
        self.providers = {}
        self.fee_schedules = {}
        self.fee_schedule_entries = {}
        self.subscribers = {}
        self.dependents = {}
        self.limitation_rules = {}
        self.predeterminations = {}
        self.claims = {}
        self.claim_lines = {}
        self.claim_attachments = {}
        self.accumulators = {}
        self.clock = CLOCK_INITIAL


# Single shared instance; nothing is ever pre-populated.
store = Store()
