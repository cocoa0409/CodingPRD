"""In-memory data store and logical clock.

The store starts empty on every boot — no seeding anywhere.
"""
import threading
from datetime import datetime, timezone

CLOCK_START_ISO = "2026-09-01T00:00:00Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp (accepts trailing Z or offset) to aware datetime."""
    if isinstance(s, datetime):
        return s
    if not isinstance(s, str):
        raise ValueError("not an ISO string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    """Format aware datetime as ISO 8601 UTC with three fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


class LogicalClock:
    def __init__(self):
        self._dt = parse_iso(CLOCK_START_ISO)
        self._lock = threading.Lock()

    def now(self):
        with self._lock:
            return self._dt

    def now_iso(self):
        return iso_z(self.now())

    def set(self, dt):
        with self._lock:
            self._dt = dt


class Store:
    def __init__(self):
        self.stores = {}
        self.product_models = {}
        self.customers = {}
        self.fit_assessments = {}
        self.orders = {}
        self.delivery_windows = {}
        self.delivery_visits = {}
        self.devices = {}
        self.sleep_nights = {}
        self.trial_returns = {}
        self.warranty_claims = {}
        self.financing_plans = {}
        self.clock = LogicalClock()
        # serialization counter so tie-break ordering on equal created_at is
        # deterministic in insertion order
        self._seq = 0
        self._lock = threading.Lock()

    def next_seq(self):
        with self._lock:
            self._seq += 1
            return self._seq


DB = Store()
