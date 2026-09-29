"""In-memory data store, logical clock and identity/timestamp helpers.

Storage is process-local Python dicts only.  Nothing is written to disk and no
entity is ever seeded: every row in here is created by an API call.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# The logical clock's default position (PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

COLLECTIONS = (
    "venues",
    "agreements",
    "submissions",
    "runs",
    "rooms",
    "slots",
    "guests",
    "orders",
    "staff",
    "shifts",
    "inspections",
    "kits",
    "statements",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# clock
# --------------------------------------------------------------------------

def now():
    """Current logical-clock instant as an aware datetime."""
    return db.clock


def today():
    """Current logical-clock UTC calendar date."""
    return db.clock.date()


def set_clock(dt):
    db.clock = dt


# --------------------------------------------------------------------------
# formatting helpers
# --------------------------------------------------------------------------

def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso(db.clock)


def new_id():
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

def new_row(versioned=True):
    """A fresh row carrying the common system fields (PRD §2.4)."""
    stamp = now_iso()
    row = {"id": new_id(), "created_at": stamp}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Record a mutation: refresh updated_at and advance version by one."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 0) + 1
    return row


def public(row):
    """Strip internal bookkeeping keys before serialisation."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ordered(rows):
    """PRD §2.3: created_at ascending with a stable tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
