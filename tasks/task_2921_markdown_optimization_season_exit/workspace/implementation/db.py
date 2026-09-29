"""In-memory data store.

Storage is process-local Python dictionaries only. Nothing is seeded, loaded
or preloaded: every boot of start.sh begins with an entirely empty store.
"""

import threading
from datetime import datetime, timezone

from common import instant_from_datetime, new_uuid, now_instant

DEFAULT_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "seasons",
    "price_zones",
    "stores",
    "items",
    "sales_weeks",
    "estimates",
    "plans",
    "steps",
    "executions",
    "reservations",
    "agreements",
    "claims",
    "dispositions",
    "exit_reviews",
)


class Database(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = DEFAULT_CLOCK_UTC
        for name in COLLECTIONS:
            setattr(self, name, {})

    # -- logical clock (PRD 2.5) -------------------------------------------
    def clock_instant(self):
        return instant_from_datetime(self.clock)

    def clock_date(self):
        return self.clock.astimezone(timezone.utc).date()

    # -- generic helpers ---------------------------------------------------
    def all(self, name):
        """Every row of a collection in insertion (created_at ascending) order."""
        return sorted(getattr(self, name).values(), key=lambda r: r["created_at"])

    def get(self, name, row_id):
        if not isinstance(row_id, str):
            return None
        return getattr(self, name).get(row_id)

    def insert(self, name, row):
        getattr(self, name)[row["id"]] = row
        return row


db = Database()


def new_row(versioned=True, **fields):
    row = {"id": new_uuid(), "created_at": now_instant()}
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """Refresh updated_at and increment version (PRD 2.4 / 2.9)."""
    if row is None or "version" not in row:
        return row
    row["updated_at"] = now_instant()
    row["version"] = row["version"] + 1
    return row


def assign(row, field, value):
    """Set a field, reporting whether the stored value actually changed."""
    if row.get(field) == value:
        return False
    row[field] = value
    return True


def apply_changes(row, changes):
    """Apply a dict of field updates; touch the row when anything changed."""
    changed = False
    for field, value in changes.items():
        if assign(row, field, value):
            changed = True
    if changed:
        touch(row)
    return changed
