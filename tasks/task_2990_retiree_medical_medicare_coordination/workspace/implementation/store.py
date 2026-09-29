"""In-memory data store and the logical UTC clock.

Nothing is persisted anywhere: every byte of state lives in the dictionaries
below and vanishes when the process exits.  The store starts completely empty on
every boot -- no entity is ever seeded, preloaded or hardcoded.
"""

import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: before any client sets it, the logical clock reads exactly this
# instant, and it must never fall back to wall-clock time.
LOGICAL_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.plan_years = {}
        self.retirees = {}
        self.plan_options = {}
        self.determinations = {}
        self.election_events = {}
        self.enrollments = {}
        self.hra_accounts = {}
        self.claims = {}
        self.invoices = {}
        self.clock = LOGICAL_CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The logical UTC clock -- the only source of time in the programme."""
    return db.clock


def set_clock(instant):
    db.clock = instant.astimezone(timezone.utc)
    return db.clock


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def base_record():
    """id / created_at / updated_at / version, common to all nine entities."""
    t = now()
    return {
        "id": new_id(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(record):
    """Every mutation refreshes updated_at and advances version by exactly 1."""
    record["updated_at"] = now()
    record["version"] += 1
    return record


def order_asc(rows):
    """created_at ascending, with insertion sequence as the stable tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def add_days(instant, days):
    return instant + timedelta(days=days)
