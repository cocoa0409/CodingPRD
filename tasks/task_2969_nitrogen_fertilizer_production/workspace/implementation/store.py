"""In-memory store.

Storage is a set of plain dicts keyed by UUID string. Nothing is persisted and
nothing is ever seeded: every row in here got there through a declared
endpoint. The harness restarts the process before each test, so a module-level
singleton is the whole lifecycle.
"""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

FAMILIES = (
    "plants",
    "trains",
    "charges",
    "lots",
    "lines",
    "runs",
    "orders",
    "assets",
    "shipments",
    "quotes",
    "turnarounds",
    "tasks",
    "readings",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in FAMILIES:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    def rows(self, family):
        """Every row of a family in created_at ascending (insertion) order."""
        return sorted(getattr(self, family).values(), key=lambda r: r["_seq"])


db = Store()


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def stamp_new(row):
    """Give a freshly built row its identity, clock stamps and version."""
    row["id"] = db.new_id()
    row["_seq"] = db.next_seq()
    row["created_at"] = db.clock
    if row.pop("_immutable", False):
        return row
    row["updated_at"] = db.clock
    row["version"] = 1
    return row


def bump(row):
    """A mutation: version advances by exactly 1 and updated_at is refreshed."""
    row["version"] = row["version"] + 1
    row["updated_at"] = db.clock
    return row
