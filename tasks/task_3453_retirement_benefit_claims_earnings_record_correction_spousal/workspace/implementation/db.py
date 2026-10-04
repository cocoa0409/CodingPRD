"""In-memory data store and the logical clock.

The store starts EMPTY on every boot: no seeding, no preloading. All entities
are created exclusively through the declared API surface. The logical clock
starts at exactly 2026-09-01T00:00:00Z and never consults wall-clock time
(PRD §2.4). Entity created_at/updated_at timestamps are stamped from the
logical clock; a monotonic per-store sequence number breaks ties for
created_at-ordered listings.
"""

import threading
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = DEFAULT_CLOCK
        self.seq = 0
        # entity tables, keyed by id
        self.workers = {}
        self.earnings_years = {}
        self.wage_reports = {}
        self.corrections = {}
        self.relationships = {}
        self.claims = {}
        self.payments = {}
        self.overpayments = {}
        self.payees = {}
        self.recomputations = {}
        # idempotency ledger for the monthly cycle: set of "YYYY-MM" strings
        self.ran_months = set()

    def next_seq(self):
        self.seq += 1
        return self.seq

    def now_iso(self):
        return fmt_ts(self.clock)

    def clock_date(self):
        return self.clock.date()

    def clock_month(self):
        return (self.clock.year, self.clock.month)


store = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_new(entity):
    """Assign id / created_at / insertion sequence to a fresh record."""
    entity["id"] = new_id()
    entity["created_at"] = store.now_iso()
    entity["_seq"] = store.next_seq()
    return entity


def stamp_common_new(entity):
    """Records with common_fields (PRD §2.6) also get updated_at + version."""
    stamp_new(entity)
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    return entity


def touch(entity):
    """Every modification (including cascaded ones) refreshes updated_at and
    increments version by one (PRD §2.6 / §2.8)."""
    entity["updated_at"] = store.now_iso()
    entity["version"] += 1


def created_key(entity):
    """created_at ASC ordering with a stable insertion-sequence tiebreak."""
    return (entity["created_at"], entity["_seq"])
