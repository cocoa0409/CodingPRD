"""In-memory store. Starts empty on every boot; nothing is ever seeded."""

import uuid

from clock import CLOCK

TABLES = (
    "production",
    "market",
    "performance",
    "allocation",
    "draw_entry",
    "purchase",
    "seat_hold",
    "queue_position",
    "desk",
    "refund",
    "exchange",
    "patron",
)

# Every resource carries the full common property set.
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def new_id():
    return str(uuid.uuid4())


class Store(object):
    def __init__(self):
        self.rows = {name: {} for name in TABLES}

    def table(self, name):
        return self.rows[name]

    def insert(self, name, row):
        if "id" not in row:
            row["id"] = new_id()
        stamp = CLOCK.stamp()
        row["created_at"] = stamp
        row["updated_at"] = stamp
        row.setdefault("version", 1)
        self.rows[name][row["id"]] = row
        return row

    def touch(self, name, row, bump=True):
        """Refresh updated_at and advance version by exactly one."""
        row["updated_at"] = CLOCK.stamp()
        if bump:
            row["version"] = row.get("version", 1) + 1
        return row

    def get(self, name, row_id):
        return self.rows[name].get(row_id)

    def all(self, name):
        return list(self.rows[name].values())


DB = Store()