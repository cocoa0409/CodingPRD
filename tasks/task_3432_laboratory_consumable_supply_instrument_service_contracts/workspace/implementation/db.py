"""In-memory data store and the server logical clock.

Storage is plain dicts keyed by id. The store starts EMPTY on every boot:
no seeding, no disk persistence, no preloaded entities. The logical clock
starts at exactly 2026-09-01T00:00:00Z and advances only via
POST /lab/_clock/set_current_utc; it never falls back to wall-clock time.
"""
import threading
from datetime import datetime, timezone

_START_CLOCK = "2026-09-01T00:00:00+00:00"


class Store:
    def __init__(self):
        self.accounts = {}
        self.agreements = {}
        self.instruments = {}
        self.contracts = {}
        self.engineers = {}
        self.service_requests = {}
        self.loaner_units = {}
        self.catalog_items = {}
        self.catalog_by_sku = {}
        self.orders = {}
        self.surge_events = {}
        self.seq = 0
        self.clock = datetime.fromisoformat(_START_CLOCK)
        self.lock = threading.RLock()

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def now():
    return store.clock
