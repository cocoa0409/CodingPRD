"""In-memory data store. The store starts empty on every boot; nothing is seeded."""

import threading
import uuid
from datetime import datetime, timezone


class Store:
    """Container for all entity dicts plus the logical clock."""

    def __init__(self):
        self.lock = threading.RLock()
        # Logical clock: fixed startup default; advanced only via
        # POST /_clock/set_current_utc. Never falls back to wall clock.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.products = {}
        self.raters = {}
        self.publications = {}
        self.agents = {}
        self.appointments = {}
        self.schedules = {}
        self.consumers = {}
        self.quotes = {}
        self.policies = {}
        self.claims = {}
        self.enrollments = {}
        self.statements = {}
        self.pools = {}
        self.payouts = {}
        self.reviews = {}
        self.placements = {}


DB = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical time (never wall clock)."""
    return DB.clock


def iso(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def touch(entity):
    """Refresh updated_at and bump version by exactly 1 (§2.4)."""
    entity["updated_at"] = now()
    entity["version"] += 1
