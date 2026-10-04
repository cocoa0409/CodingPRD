"""In-memory data store and the logical clock.

The store starts completely empty on every boot. The logical clock defaults to
2026-09-01T00:00:00Z and is only advanced through the test-driving endpoint.
"""
import threading
from datetime import datetime, timezone


class LogicalClock:
    START_DEFAULT = "2026-09-01T00:00:00+00:00"

    def __init__(self):
        self._lock = threading.Lock()
        self._now = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def now(self):
        with self._lock:
            return self._now

    def set(self, dt):
        with self._lock:
            self._now = dt


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = LogicalClock()
        self.affiliates = {}
        self.catalog_entries = {}
        self.fee_tiers = {}
        self.patients = {}
        self.assessments = {}
        self.providers = {}
        self.licenses = {}
        self.encounters = {}
        self.claims = {}
        self.stock_lots = {}
        self.reservations = {}
        self.referrals = {}
        self.grant_reports = {}
        self.privacy_holds = {}


store = Store()
