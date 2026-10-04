"""In-memory data store. All state lives in module-level dicts keyed by id.
The store starts completely empty on every boot; nothing is seeded.
"""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.care_programs = {}
        self.payer_contracts = {}
        self.pcp_providers = {}
        self.clinicians = {}
        self.members = {}
        self.enrollments = {}
        self.care_teams = {}
        self.visits = {}
        self.assessments = {}
        self.episodes = {}
        self.measurements = {}
        self.settlements = {}
        self.medical_costs = {}
        # Logical clock: initialized at startup per PRD §2.4; MUST NOT fall back
        # to real wall-clock time before the first operator-driven set.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()
