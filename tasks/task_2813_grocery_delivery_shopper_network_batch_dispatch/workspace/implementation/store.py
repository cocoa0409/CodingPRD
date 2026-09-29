"""In-memory data store, logical clock and row bookkeeping.

Storage is process-local Python dicts keyed by id.  Nothing is persisted and
nothing is seeded: every row is created through a declared endpoint.
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.5: before any client sets it the logical clock reads exactly this.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "retailers",
    "catalog_items",
    "customers",
    "shoppers",
    "shopper_ratings",
    "orders",
    "order_lines",
    "batches",
    "batch_orders",
    "replacements",
    "payouts",
    "credits",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical-clock instant (never wall-clock time)."""
    return db.clock


def set_clock(dt):
    db.clock = dt


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_ts():
    return fmt_ts(datetime.now(timezone.utc))


def parse_ts(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def minutes(n):
    return timedelta(minutes=n)


def hours(n):
    return timedelta(hours=n)


def base_row(with_version=True):
    ts = now()
    row = {"id": new_id(), "created_at": ts, "_seq": db.next_seq()}
    if with_version:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation: refresh updated_at and bump version once per request.

    PRD 2.4 says version increases by exactly 1 on every mutation of the row,
    and PRD 3.x describes each operation as increasing a row's version by 1 —
    so a single request that rewrites several derived fields of one row still
    bumps that row's version exactly once.
    """
    from flask import g

    if "version" not in row:
        return
    row["updated_at"] = now()
    touched = getattr(g, "touched_rows", None)
    if touched is None:
        touched = set()
        g.touched_rows = touched
    if row["id"] in touched:
        return
    touched.add(row["id"])
    row["version"] = row["version"] + 1


def sort_key(row):
    return (row["created_at"], row["_seq"])


def all_rows(collection):
    """Rows of a collection ordered by created_at ascending (stable)."""
    return sorted(collection.values(), key=sort_key)
