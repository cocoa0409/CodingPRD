"""In-memory store.  Nothing is ever seeded: every collection starts empty on
each boot and no state is written to disk."""

import threading
import uuid
from datetime import timedelta

import timeutil

COLLECTIONS = (
    "campaigns", "slots", "experts", "briefs", "items", "gates",
    "claims", "evidence", "assets", "usages", "distributions", "snapshots",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = timeutil.parse_instant(timeutil.DEFAULT_CLOCK)
        self._last_stamp = None

    def new_id(self):
        return str(uuid.uuid4())

    def stamp(self):
        """A strictly increasing wall-clock stamp so created_at ordering is stable."""
        dt = timeutil.now_wall()
        if self._last_stamp is not None and dt <= self._last_stamp:
            dt = self._last_stamp + timedelta(milliseconds=1)
        self._last_stamp = dt
        return dt


store = Store()


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


def touch(row):
    """Refresh updated_at and increment version, at most once per request per row
    (PRD section 2.9: every row a step actually changes gets exactly one bump)."""
    from flask import g
    seen = getattr(g, "touched", None)
    if seen is None:
        seen = set()
        g.touched = seen
    key = (row.get("_kind"), row.get("id"))
    if key in seen:
        return
    seen.add(key)
    row["updated_at"] = store.stamp()
    row["version"] = row["version"] + 1


def new_row(kind, fields):
    row = {"_kind": kind, "id": store.new_id(), "created_at": store.stamp()}
    row.update(fields)
    if kind not in ("evidence", "snapshots"):
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row
