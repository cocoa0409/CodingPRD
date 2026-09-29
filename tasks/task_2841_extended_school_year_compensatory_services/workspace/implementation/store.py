"""In-memory data store and the logical clock (PRD section 2.4 / 2.5).

Storage is process memory only: plain dicts keyed by id. Nothing is seeded --
every record in every collection is created by an API call.
"""
import threading
import uuid
from datetime import datetime, timedelta, timezone

LOCK = threading.RLock()

# PRD 2.5: before any client sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z. The server never falls back to real system time.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.students = {}
        self.determinations = {}
        self.programs = {}
        self.providers = {}
        self.commitments = {}
        self.assignments = {}
        self.runs = {}
        self.logs = {}
        self.awards = {}
        self.sessions = {}
        self.allocations = {}
        self.records = {}
        self.clock = INITIAL_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The current logical-clock instant."""
    return db.clock


def iso_instant(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso_instant(db.clock)


def today():
    """Calendar date portion of the logical clock, in UTC."""
    return db.clock.astimezone(timezone.utc).date()


def new_id():
    return str(uuid.uuid4())


def new_record(kind, fields):
    """Create a record carrying the four common properties of PRD 2.4."""
    stamp = now_iso()
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = stamp
    rec["updated_at"] = stamp
    rec["version"] = 1
    rec["_kind"] = kind
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Register a mutation: version += 1 and updated_at refreshed."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return rec


def creation_order(records):
    """created_at ASC with insertion sequence as the stable tie-break."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def add_days(d, n):
    return d + timedelta(days=n)
