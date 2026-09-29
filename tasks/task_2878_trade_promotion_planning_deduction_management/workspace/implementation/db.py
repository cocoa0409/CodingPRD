"""In-memory store, id/timestamp minting and the logical clock.

The store starts EMPTY on every boot: nothing is seeded, preloaded or
hardcoded.  Every row is created through a declared endpoint.
"""

import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# PRD 2.4: the logical clock starts at this fixed instant and never falls back
# to the host's real time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "programs",
    "brands",
    "customers",
    "allocations",
    "promotions",
    "tactics",
    "documents",
    "facts",
    "accruals",
    "deductions",
    "disputes",
    "analyses",
    "audits",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self.clock = DEFAULT_CLOCK

    def next_seq(self):
        return next(self._seq)


db = Store()


# --------------------------------------------------------------------------
# instants
# --------------------------------------------------------------------------

def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def real_now():
    """Wall clock, used only for created_at/updated_at audit stamps and the
    envelope's api_request_timestamp."""
    return fmt_instant(datetime.now(timezone.utc))


def clock_dt():
    return db.clock


def clock_instant():
    return fmt_instant(db.clock)


def clock_date():
    return db.clock.astimezone(timezone.utc).date()


def set_clock(dt):
    db.clock = dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def new_row(versioned=True):
    stamp = real_now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "_seq": db.next_seq(),
    }
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touched_set():
    if not hasattr(g, "_touched_rows"):
        g._touched_rows = set()
    return g._touched_rows


def touch(row):
    """Bump version/updated_at once per request for this row (PRD 2.4)."""
    if row is None:
        return row
    seen = touched_set()
    key = id(row)
    if key in seen:
        return row
    seen.add(key)
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = real_now()
    return row


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def days(n):
    return timedelta(days=n)
