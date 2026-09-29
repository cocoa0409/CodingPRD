"""In-memory data store and the system logical clock.

PRD 2.4: "Time in this system is a logical clock, never the host's wall clock."
The store starts completely empty on every boot - nothing is seeded.
"""
import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4: the clock "starts at 2026-08-01T00:00:00Z on a fresh boot".
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.issuers = {}
        self.firms = {}
        self.deals = {}
        self.tranches = {}
        self.enhancements = {}
        self.statements = {}
        self.sections = {}
        self.undertakings = {}
        self.engagements = {}
        self.presentations = {}
        self.members = {}
        self.periods = {}
        self.orders = {}
        self.documents = {}
        self.clock = CLOCK_START
        self._counter = itertools.count(1)


db = Store()


def now():
    """The current value of the logical clock."""
    return db.clock


def set_clock(value):
    db.clock = value


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db._counter)


def new_row(**fields):
    """Create a row carrying the four common fields of PRD 2.4."""
    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    """PRD 2.4: a mutated row refreshes updated_at and increments version by 1."""
    row["updated_at"] = now()
    row["version"] = row["version"] + 1


def values(table):
    return list(table.values())
