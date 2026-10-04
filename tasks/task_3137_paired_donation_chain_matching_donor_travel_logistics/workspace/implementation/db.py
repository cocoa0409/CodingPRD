"""In-memory data store and logical clock. Store starts empty on every boot."""

import threading
import uuid
from datetime import datetime, timezone

from constants import CLOCK_DEFAULT_ISO


def parse_iso(value):
    """Parse an ISO-8601 timestamp (accepting trailing Z) to an aware datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id():
    return str(uuid.uuid4())


class Store:
    """All entity tables plus the logical clock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.centers = {}
        self.donors = {}
        self.recipients = {}
        self.pairs = {}
        self.chain_runs = {}
        self.chains = {}
        self.offers = {}
        self.reviews = {}
        self.slots = {}
        self.shipments = {}
        self.itineraries = {}
        self.policies = {}
        self.claims = {}
        self.outcomes = {}
        self.chain_breaks = {}
        self._clock = parse_iso(CLOCK_DEFAULT_ISO)

    # --- logical clock ---
    def now(self):
        return self._clock

    def now_iso(self):
        return iso_z(self._clock)

    def set_clock(self, dt):
        self._clock = dt

    # --- generic entity helpers ---
    def stamp_new(self, rec):
        ts = self.now_iso()
        rec["id"] = new_id()
        rec["created_at"] = ts
        rec["updated_at"] = ts
        rec["version"] = 1
        return rec

    def touch(self, rec):
        """Mutation: refresh updated_at and bump version."""
        rec["updated_at"] = self.now_iso()
        rec["version"] = rec.get("version", 1) + 1
        return rec

    def insert(self, table, rec):
        self.stamp_new(rec)
        table[rec["id"]] = rec
        return rec


store = Store()
