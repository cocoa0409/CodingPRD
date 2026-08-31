"""In-memory store, logical clock, id / timestamp helpers.

Storage is process-local Python dicts keyed by id. Nothing is persisted and
nothing is seeded: every table starts empty on every boot.
"""

import datetime as _dt
import random
import string
import threading
import uuid

LOCK = threading.RLock()

CLOCK_EPOCH = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)

# ---------------------------------------------------------------- tables
TABLES = (
    "athletes",
    "brands",
    "opportunities",
    "term_sheets",
    "engagements",
    "exclusivity_grants",
    "appearance_bookings",
    "production_slots",
    "deliverables",
    "disclosure_records",
    "payout_statements",
    "renewal_options",
    "ledger_entries",
)


class _Store(object):
    def __init__(self):
        for name in TABLES:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = _Store()


# ---------------------------------------------------------------- clock
def now():
    """The logical clock. Never falls back to wall-clock time."""
    return db.clock


def set_clock(value):
    db.clock = value
    return db.clock


# ------------------------------------------------------- id / timestamps
def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    value = value.astimezone(_dt.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
        value.microsecond // 1000,
    )


def fmt_date(value):
    if value is None:
        return None
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def stamp():
    return fmt_dt(now())


# ---------------------------------------------------------------- records
def new_record(extra=None, common=True):
    rec = {"id": new_id()}
    if common:
        ts = stamp()
        rec["created_at"] = ts
        rec["updated_at"] = ts
        rec["version"] = 1
    else:
        rec["created_at"] = stamp()
    rec["_seq"] = db.next_seq()
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """A mutation (direct or cascaded) bumps updated_at and version."""
    if rec is None:
        return rec
    rec["updated_at"] = stamp()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_rows(rows):
    """Default ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
