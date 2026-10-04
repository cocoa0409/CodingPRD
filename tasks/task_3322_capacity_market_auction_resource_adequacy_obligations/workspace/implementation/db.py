"""In-memory data store. Starts empty on every boot — no seeding."""
import threading
from datetime import datetime, timezone, timedelta


class LogicalClock:
    """Logical clock: starts at 2026-09-01T00:00:00Z, never uses wall clock."""

    EPOCH = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

    def __init__(self):
        self._current = self.EPOCH
        self._seq = 0
        self._lock = threading.Lock()

    def now(self):
        with self._lock:
            # Guarantee strictly-increasing timestamps within a process so that
            # ordering by created_at is stable even for back-to-back writes.
            candidate = self._current + timedelta(milliseconds=self._seq)
            self._seq += 1
            return candidate

    def set_current(self, dt):
        with self._lock:
            self._current = dt
            self._seq = 0

    def current(self):
        with self._lock:
            return self._current + timedelta(milliseconds=self._seq)


class DB:
    def __init__(self):
        self.clock = LogicalClock()
        # entity stores: id -> dict
        self.delivery_years = {}
        self.zones = {}
        self.forecasts = {}
        self.owners = {}
        self.resources = {}
        self.accreditations = {}
        self.auction_runs = {}
        self.offers = {}
        self.mitigation_reviews = {}
        self.commitments = {}
        self.replacements = {}
        self.emergency_events = {}
        self.assessments = {}
        self.measurement_reports = {}
        self.settlement_entries = {}


db = DB()
