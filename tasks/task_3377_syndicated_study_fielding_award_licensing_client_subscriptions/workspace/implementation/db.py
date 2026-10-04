"""In-memory data store and the logical clock.

The store starts completely empty on every boot; tests construct all state
through the declared API surface. The logical clock never falls back to
wall-clock time and reads exactly 2026-09-01T00:00:00Z until set.
"""
import itertools
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.studies = {}
        self.methodology_versions = {}
        self.factors = {}
        self.sample_frames = {}
        self.responses = {}
        self.brand_results = {}
        self.awards = {}
        self.licenses = {}
        self.usage_audits = {}
        self.clients = {}
        self.brands = {}
        self.subscriptions = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()
