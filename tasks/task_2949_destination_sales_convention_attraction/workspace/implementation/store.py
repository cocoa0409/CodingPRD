"""In-memory data store and the server-controlled logical clock.

Everything lives in plain dicts keyed by the server-minted uuid.  The store is
empty on every boot: no entity is ever seeded, preloaded or hardcoded.
"""

import datetime
import uuid

from util import UTC

# PRD 2.4 / scaffold DEFAULT_CLOCK_UTC: the clock's startup default is exactly
# 2026-08-01T00:00:00Z and the server never falls back to wall-clock time.
DEFAULT_CLOCK = datetime.datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "planners",
    "hotels",
    "halls",
    "opportunities",
    "space_holds",
    "commitments",
    "bid_packages",
    "support_letters",
    "funds",
    "receipts",
    "decisions",
    "estimates",
    "servicing_orders",
    "pickup_records",
    "board_reports",
)


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    # -- identity / ordering ------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_row(self, versioned=True):
        """A fresh row carrying the common fields of PRD 2.4."""
        row = {
            "id": str(uuid.uuid4()),
            "created_at": self.clock,
            "_seq": self.next_seq(),
        }
        if versioned:
            row["updated_at"] = self.clock
            row["version"] = 1
        return row


db = Store()


def touch(row):
    """One cascade hop mutating a versioned row: bump version, refresh updated_at."""
    if row is None or "version" not in row:
        return row
    row["version"] += 1
    row["updated_at"] = db.clock
    return row


def ordered(rows):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
