"""In-memory data store and the server-held logical clock.

Everything lives in plain dicts keyed by id. The store starts completely empty
on every boot -- no entity is ever seeded, preloaded or hardcoded.
"""
import uuid
from datetime import datetime, timezone

UTC = timezone.utc
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self.payers = {}
        self.patients = {}
        self.plans = {}
        self.authorizations = {}
        self.nurses = {}
        self.competencies = {}
        self.cases = {}
        self.shifts = {}
        self.assignments = {}
        self.timesheets = {}
        self.visits = {}
        self.incidents = {}
        self.disputes = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """Every business timestamp reads the logical clock, never the wall clock."""
    return db.clock


def new_row(**fields):
    row = {
        "id": str(uuid.uuid4()),
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    return row


def new_immutable_row(**fields):
    """A row that carries only id and created_at (SupervisoryVisit)."""
    row = {"id": str(uuid.uuid4()), "created_at": db.clock, "_seq": db.next_seq()}
    row.update(fields)
    return row


def touch(row):
    """Refresh updated_at and increment version on a mutated row."""
    if row is None:
        return
    row["updated_at"] = db.clock
    if "version" in row:
        row["version"] = int(row["version"]) + 1


def ordered(table):
    """Rows sorted by created_at ascending; insertion order breaks exact ties."""
    return sorted(table.values(), key=lambda r: (r["created_at"], r["_seq"]))
