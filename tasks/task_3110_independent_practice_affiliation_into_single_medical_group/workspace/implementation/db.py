"""In-memory data store. Store starts empty on every boot; the logical clock
starts at exactly 2026-09-01T00:00:00Z and never falls back to wall-clock."""

import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.medical_groups = {}
        self.markets = {}
        self.practices = {}
        self.providers = {}
        self.agreements = {}
        self.waves = {}
        self.payer_contracts = {}
        self.fee_schedule_rates = {}
        self.enrollments = {}
        self.batches = {}
        self.statements = {}
        self.pools = {}
        self.allocations = {}
        self.departure_cases = {}
        self.votes = {}
        # Logical clock: fixed default, advanced only via /_clock/set_current_utc
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

    def clock_date(self):
        return self.clock.date()

    def set_clock(self, dt):
        self.clock = dt


store = Store()
