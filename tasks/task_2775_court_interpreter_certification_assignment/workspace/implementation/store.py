"""In-memory data store and the server-held logical clock.

Every entity lives in a plain dict keyed by its `id`.  Nothing is persisted and
nothing is seeded: a fresh process starts with an empty program and the logical
clock reading the fixed startup default.
"""
from util import CLOCK_DEFAULT, fmt_dt, new_uuid, parse_dt

COLLECTIONS = (
    "languages",
    "courthouses",
    "rate_schedules",
    "interpreters",
    "credentials",
    "exam_attempts",
    "hearings",
    "assignments",
    "pay_claims",
    "complaints",
    "disciplinary_actions",
    "unmet_need_reports",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_dt(CLOCK_DEFAULT)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The current logical-clock instant."""
    return db.clock


def today():
    """The UTC calendar date of the logical clock."""
    return db.clock.date()


def new_row(common=True):
    """A fresh row carrying identity, timestamps and a revision counter.

    `common=False` produces an immutable ledger entry: only `id` and
    `created_at`, with no `updated_at` and no `version` at all.
    """
    row = {"id": new_uuid(), "created_at": fmt_dt(now()), "_seq": db.next_seq()}
    if common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation: refresh `updated_at` and add 1 to `version`."""
    row["updated_at"] = fmt_dt(now())
    row["version"] = row.get("version", 1) + 1
    return row


def sort_created(rows):
    """Deterministic `created_at` ascending order."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
