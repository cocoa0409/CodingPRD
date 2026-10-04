"""In-memory data store and server-held logical clock.

The store is module-level and starts completely empty on every boot. No
entity is seeded anywhere. The logical clock defaults to exactly
2026-09-01T00:00:00Z and never falls back to wall-clock time.
"""

import functools
import threading
import uuid
from datetime import datetime, timezone

from util import fmt_ts

DEFAULT_CLOCK_RAW = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0
        # Logical clock: raw string (echoed verbatim) + parsed datetime.
        self.clock_raw = DEFAULT_CLOCK_RAW
        self.clock_dt = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Entity tables: dict keyed by id. All start empty.
        self.households = {}
        self.members = {}
        self.terms = {}
        self.providers = {}
        self.agreements = {}
        self.statements = {}
        self.complaints = {}
        self.entities = {}
        self.transfers = {}
        self.publications = {}
        self.bookings = {}
        self.chapters = {}
        self.sessions = {}
        self.campaigns = {}
        self.mobilizations = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def mint(table):
    """Create a bare record with common system fields and insert it."""
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": fmt_ts(store.clock_dt),
        "updated_at": fmt_ts(store.clock_dt),
        "version": 1,
        "_seq": store.next_seq(),
    }
    table[rec["id"]] = rec
    return rec


def touch(rec):
    """Record a mutation: bump optimistic-concurrency version + updated_at."""
    rec["version"] += 1
    rec["updated_at"] = fmt_ts(store.clock_dt)


def locked(fn):
    """Serialize a request handler against the store (check-then-act safety)."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with store.lock:
            return fn(*args, **kwargs)

    return wrapper
