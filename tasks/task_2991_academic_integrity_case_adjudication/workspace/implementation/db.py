"""In-memory data store.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded. Every row is created through the declared endpoints.
PRD section 2.4: the logical clock reads 2026-08-01T00:00:00Z before any
client moves it, and nothing in this system reads the wall clock.
"""

import uuid
from datetime import datetime

from util import UTC

DEFAULT_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "departments",
    "faculty_members",
    "training_completions",
    "students",
    "offerings",
    "reports",
    "evidence_items",
    "cases",
    "notifications",
    "engagements",
    "meetings",
    "rooms",
    "sessions",
    "votes",
    "sanctions",
    "appeals",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK_UTC
        self.seq = 0
        self.case_seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})


S = Store()


def now():
    return S.clock


def next_seq():
    S.seq += 1
    return S.seq


def new_row(**fields):
    """A row carrying the full set of system-managed properties (PRD 2.5)."""
    row = {
        "id": str(uuid.uuid4()),
        "_seq": next_seq(),
        "created_at": S.clock,
        "updated_at": S.clock,
        "version": 1,
    }
    row.update(fields)
    return row


def new_immutable_row(**fields):
    """EvidenceItem / PanelVote rows carry only id and created_at (PRD 2.5)."""
    row = {
        "id": str(uuid.uuid4()),
        "_seq": next_seq(),
        "created_at": S.clock,
    }
    row.update(fields)
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly one."""
    row["updated_at"] = S.clock
    row["version"] = row["version"] + 1


def ordered(collection):
    """Rows sorted by created_at ascending (insertion sequence breaks ties)."""
    if isinstance(collection, dict):
        rows = list(collection.values())
    else:
        rows = list(collection)
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def next_case_number():
    S.case_seq += 1
    return "AIC-%06d" % S.case_seq
