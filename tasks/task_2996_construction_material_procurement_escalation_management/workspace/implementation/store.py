"""In-memory store. Empty on every boot - no seeding, no persistence."""

import uuid

from util import CLOCK_DEFAULT

COLLECTIONS = (
    "projects",
    "packages",
    "suppliers",
    "quotes",
    "agreements",
    "index_readings",
    "commitments",
    "arrangements",
    "documents",
    "substitutions",
    "change_orders",
    "disruptions",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_row(self, versioned=True):
        row = {
            "id": str(uuid.uuid4()),
            "created_at": self.clock,
            "_seq": self.next_seq(),
        }
        if versioned:
            row["updated_at"] = self.clock
            row["version"] = 1
        return row

    def touch(self, row):
        """Record a mutation of a row: refresh updated_at, bump version by 1."""
        if "version" in row:
            row["updated_at"] = self.clock
            row["version"] = row["version"] + 1
        return row


store = Store()


def ordered(rows):
    """Creation order: created_at ascending, insertion sequence as the tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
