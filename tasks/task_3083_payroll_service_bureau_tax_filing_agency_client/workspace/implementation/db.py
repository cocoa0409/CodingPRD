"""In-memory data store. Starts completely empty on every boot."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.jurisdictions = {}
        self.clients = {}
        self.registrations = {}
        self.payroll_runs = {}
        self.impounds = {}
        self.funding_failures = {}
        self.deposits = {}
        self.returns = {}
        self.amendments = {}
        self.notices = {}
        self.credit_assessments = {}
        self.wage_statements = {}
        # Logical clock: fixed start, never falls back to wall clock.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Monotonic creation sequence used as a stable sort tiebreaker
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq
        # Monotonic creation sequence used as a stable sort tiebreaker
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()
