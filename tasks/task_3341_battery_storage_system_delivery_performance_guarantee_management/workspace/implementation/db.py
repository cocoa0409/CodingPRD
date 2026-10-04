"""In-memory data store. Fresh on every process boot; nothing is seeded."""
from datetime import datetime, timezone

# Logical clock default per PRD §2.4
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        self.projects = {}
        self.esas = {}
        self.milestones = {}
        self.permits = {}
        self.tests = {}
        self.augmentations = {}
        self.service_agreements = {}
        self.orders = {}
        self.claims = {}
        self.bid_sessions = {}
        self._clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

    def clock(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


store = Store()
