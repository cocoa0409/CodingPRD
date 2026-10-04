"""In-memory data store. The store starts empty on every boot; nothing is seeded."""

import threading
import uuid
from datetime import datetime, timezone


class Store:
    """Container for all entity dicts and the logical clock."""

    def __init__(self):
        self.lock = threading.RLock()
        # Logical clock: fixed default, advanced only via POST /api/_clock/set_current_utc.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Entity collections keyed by id.
        self.stores = {}
        self.articles = {}
        self.cartons = {}
        self.bin_stock = {}
        self.customers = {}
        self.orders = {}
        self.order_lines = {}
        self.reservations = {}
        self.delivery_slots = {}
        self.delivery_bookings = {}
        self.assembly_standards = {}
        self.assembly_jobs = {}
        self.spare_part_claims = {}
        self.return_requests = {}
        self.return_lines = {}


DB = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical time (never wall-clock)."""
    return DB.clock


def iso(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    s = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return s


def touch(entity):
    """Refresh updated_at and bump version by exactly 1 (per §2.4)."""
    entity["updated_at"] = now()
    entity["version"] += 1
