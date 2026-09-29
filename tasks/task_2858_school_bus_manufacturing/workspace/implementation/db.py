"""In-memory data store, logical clock, record helpers.

Storage is process-local Python dicts keyed by id.  Nothing is persisted and
nothing is seeded: every collection starts empty on every boot.
"""

import uuid
from datetime import datetime, timedelta, timezone

from flask import g

from errors import ApiError

# PRD 2.4: the logical clock starts at exactly this instant on every boot.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "profiles",
    "models",
    "packages",
    "solicitations",
    "bids",
    "revisions",
    "orders",
    "lines",
    "slots",
    "units",
    "bays",
    "tests",
    "dealers",
    "campaigns",
    "tasks",
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


# ---------------------------------------------------------------- timestamps

def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt_instant(db.clock)


def now_dt():
    return db.clock


def today():
    return db.clock.date()


def fmt_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def date_plus(d, days):
    return d + timedelta(days=days)


# ------------------------------------------------------------------- records

def new_id():
    return str(uuid.uuid4())


def make_record(fields, versioned=True):
    """Build a record: id first, then payload, then the system fields."""
    rec = {"id": new_id()}
    rec.update(fields)
    stamp = now_iso()
    rec["created_at"] = stamp
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Mark a record mutated: refresh updated_at and bump version.

    At most one bump per record per HTTP request, so a cascade that visits the
    same record twice still advances the version exactly once.
    """
    if rec is None:
        return rec
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    key = id(rec)
    if key in touched:
        return rec
    touched.add(key)
    rec["updated_at"] = now_iso()
    rec["version"] = int(rec.get("version", 1)) + 1
    return rec


def public(rec):
    return dict((k, v) for k, v in rec.items() if not k.startswith("_"))


def public_list(recs):
    return [public(r) for r in recs]


def by_creation(recs):
    """Default list ordering: created_at ascending, insertion order as tie-break."""
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))


def get_or_404(collection, rec_id, error_id):
    if not isinstance(rec_id, str):
        raise ApiError(error_id)
    rec = collection.get(rec_id)
    if rec is None:
        raise ApiError(error_id)
    return rec


def values(collection):
    return list(collection.values())
