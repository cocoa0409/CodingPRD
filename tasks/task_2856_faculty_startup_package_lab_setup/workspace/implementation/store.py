"""In-memory data store, logical clock and audit-field helpers.

The store starts EMPTY on every boot: nothing is seeded, preloaded or hardcoded.
Every entity is built by a client through the declared API surface.
"""

import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone

# The logical clock's startup default (PRD 2.5). It must never fall back to
# wall-clock time before the first client call.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.funding_units = {}
        self.faculty = {}
        self.packages = {}
        self.tranches = {}
        self.lab_spaces = {}
        self.space_assignments = {}
        self.renovation_projects = {}
        self.renovation_phases = {}
        self.equipment_orders = {}
        self.staff_appointments = {}
        self.spend_transactions = {}
        # creation-ordered list of ledger row ids (the canonical reading order)
        self.txn_order = []
        self.clock = CLOCK_DEFAULT
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def now():
    """Read the logical clock."""
    return db.clock


def set_clock(instant):
    db.clock = instant


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def iso(instant):
    """ISO 8601 UTC with exactly three fractional digits."""
    if instant is None:
        return None
    if instant.tzinfo is not None:
        instant = instant.astimezone(timezone.utc)
    return instant.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (instant.microsecond // 1000)


def add_days(instant, days):
    return instant + timedelta(days=int(days))


def stamp_new(record):
    """Apply the audit triple to a brand-new resource."""
    ts = iso(now())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


# ---------------------------------------------------------------------------
# Mutation bookkeeping.  A resource's version increments by exactly one per
# request that mutates it (including mutations the server performs on its own
# initiative as part of a cascade, and recomputation of a derived field).
# ---------------------------------------------------------------------------
_touched = set()


def begin_request():
    _touched.clear()


def touch(record):
    if record is None:
        return record
    key = id(record)
    if key in _touched:
        record["updated_at"] = iso(now())
        return record
    _touched.add(key)
    record["updated_at"] = iso(now())
    record["version"] = int(record.get("version", 1)) + 1
    return record


def sort_key(record):
    """Default list ordering: created_at ascending (stable by insertion seq)."""
    return (record.get("created_at") or "", record.get("_seq", 0))


def by_created(records):
    return sorted(records, key=sort_key)
