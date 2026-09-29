"""In-memory data store. Nothing is seeded: every dict starts empty and all
state vanishes when the process exits."""
import uuid
from datetime import datetime

from util import UTC

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.plant = None
        self.contracts = {}
        self.deliveries = {}
        self.batches = {}
        self.health_readings = {}
        self.tanks = {}
        self.blends = {}
        self.tracks = {}
        self.shipments = {}
        self.sales = {}
        self.rins = {}
        self.projects = {}
        self.positions = {}
        self.conditions = {}
        self.permit_readings = {}
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


def new_row(extra=None, versioned=True):
    row = {
        "id": db.new_id(),
        "created_at": db.clock,
        "_seq": db.next_seq(),
    }
    if versioned:
        row["updated_at"] = db.clock
        row["version"] = 1
    if extra:
        row.update(extra)
    return row


def touch(row):
    row["updated_at"] = db.clock
    row["version"] = row.get("version", 1) + 1
    return row


def ordered(rows, key=None, reverse=False):
    """Deterministic ordering with the insertion sequence as final tiebreak."""
    if key is None:
        key = lambda r: ()
    return sorted(rows, key=lambda r: tuple(key(r)) + (r["_seq"],), reverse=reverse)


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
