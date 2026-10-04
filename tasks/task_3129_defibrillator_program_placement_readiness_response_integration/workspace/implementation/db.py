"""In-memory data store and logical clock.

The store starts empty on every boot — no seeding. All entities are created
through the declared API surface.
"""

import threading
from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.campuses = {}
        self.zones = {}
        self.device_models = {}
        self.cabinets = {}
        self.devices = {}
        self.consumable_lots = {}
        self.installs = {}
        self.inspections = {}
        self.self_test_reports = {}
        self.responders = {}
        self.training_sessions = {}
        self.emergency_events = {}
        self.case_reviews = {}
        self.replenishment_orders = {}
        self._clock = datetime(2026, 9, 1, tzinfo=timezone.utc)

    # --- logical clock -----------------------------------------------------
    def now(self) -> datetime:
        return self._clock

    def set_clock(self, dt: datetime) -> None:
        self._clock = dt


db = Store()
