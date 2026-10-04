"""In-memory data store.

Everything lives in process memory: plain dicts keyed by id.  Nothing is ever
written to disk, to /tmp or to any cache, so a fresh ``start.sh`` invocation
always boots into a pristine, empty database.  No entity is seeded here or
anywhere else at startup -- every row a test needs is created through the
declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

# The logical clock reads this fixed instant before any call to
# POST /_clock/set_current_utc and it never falls back to real wall-clock time.
DEFAULT_NOW = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "stores",
    "customers",
    "registry",
    "regulations",
    "vendor_shops",
    "bundles",
    "credit_applications",
    "promotional_plans",
    "ledger",
    "diamonds",
    "registrations",
    "visits",
    "repairs",
    "holds",
    "appraisals",
    "purchases",
    "designs",
    "statements",
)

# Collections whose rows carry the full common field set (id, created_at,
# updated_at, version).  PayoffLedgerEntry and RepairHold deliberately carry
# only id and created_at: they are immutable single-event records.
NO_VERSION = {"ledger", "holds"}


class Store(object):
    def __init__(self):
        self.clear()

    def clear(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.seq = itertools.count(1)
        self.clock = DEFAULT_NOW
        # plan_id -> cumulative magnitude of payments applied to quarters
        self.quarter_payments = {}

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self.seq)

    def now(self):
        return self.clock

    def add(self, collection, row):
        getattr(self, collection)[row["id"]] = row
        return row

    def get(self, collection, ident):
        return getattr(self, collection).get(ident)

    def all(self, collection):
        return list(getattr(self, collection).values())

    def where(self, collection, **filters):
        out = []
        for row in self.all(collection):
            if all(row.get(k) == v for k, v in filters.items()):
                out.append(row)
        return out


DB = Store()


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------

def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


R = iso  # shorthand used all over the codebase


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Returns None when the value is not a usable instant; callers turn that
    into ERR_INVALID_REQUEST.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days_between(later, earlier):
    """Whole days between two instants, floored."""
    return int((later - earlier).total_seconds() // 86400)