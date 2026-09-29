"""In-memory data store and the system logical clock.

Storage is process-local Python dicts keyed by id. Nothing is persisted to
disk and NOTHING is seeded at startup: every row is created by an API call.
"""
import uuid
from datetime import datetime, timezone

# PRD 2.5: at server start the logical clock reads exactly 2026-08-01T00:00:00Z
# and must never fall back to real wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "agencies",
    "sites",
    "templates",
    "units",
    "keysets",
    "campaigns",
    "talkgroups",
    "patches",
    "site_events",
    "talkpaths",
    "change_requests",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current instant of the logical clock."""
    return store.clock


def rows(collection):
    """All rows of a collection in stable creation order."""
    return sort_rows(list(getattr(store, collection).values()))


def sort_rows(items):
    # PRD 2.3: list rows are sorted by created_at ascending. Rows created in
    # the same logical instant keep their insertion order (_seq tie-break).
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def base_row(extra=None):
    ts = now()
    row = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def touch(row):
    """Mark a row mutated: refresh updated_at, and bump version once per request.

    PRD 2.5/2.7: every mutation -- including a mutation caused by a cascade and
    including the recomputation of a derived field -- refreshes updated_at and
    increments version by one. A single operation that writes several fields of
    the same row is one mutation, so the counter advances at most once per
    request for any given row.
    """
    from flask import g
    row["updated_at"] = now()
    touched = getattr(g, "touched_rows", None)
    if touched is None:
        touched = set()
        g.touched_rows = touched
    if row["id"] not in touched:
        touched.add(row["id"])
        row["version"] += 1
    return row
