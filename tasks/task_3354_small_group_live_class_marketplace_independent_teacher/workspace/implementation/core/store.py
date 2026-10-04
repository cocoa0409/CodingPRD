"""In-memory data store.

Pure Python dictionaries keyed by id. Nothing is ever persisted to disk, and
nothing is seeded at import time: every record is created through a declared
endpoint. Re-launching start.sh therefore wipes every byte of state.
"""

import uuid

from . import clock

COLLECTIONS = (
    "applications",
    "teachers",
    "listings",
    "sections",
    "learners",
    "enrollments",
    "payouts",
    "reports",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


def coll(name):
    return getattr(DB, name)


# ---------------------------------------------------------------------------
# Request-scoped write bookkeeping
# ---------------------------------------------------------------------------
_touched = set()
_active = False


def begin_request():
    global _touched, _active
    _touched = set()
    _active = True


def end_request():
    global _touched, _active
    _touched = set()
    _active = False


def mark_dirty(obj):
    """Register that `obj` will be mutated by the current request."""
    if obj is not None:
        _touched.add(id(obj))


def touch(obj):
    """Refresh updated_at and advance version exactly once per request.

    PRD section 2.5: any write to a persisted field — including a recomputed
    derived field — refreshes updated_at and advances version.
    """
    if obj is None:
        return obj
    if _active:
        if id(obj) in _touched:
            return obj
        _touched.add(id(obj))
    obj["updated_at"] = clock.fmt(clock.now())
    obj["version"] = obj.get("version", 1) + 1
    return obj


def new_id():
    return str(uuid.uuid4())


def make_record(collection, **fields):
    """Create a fresh record carrying the four common properties."""
    stamp = clock.fmt(clock.now())
    record = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": DB.next_seq(),
        "_internal": {},
    }
    record.update(fields)
    coll(collection)[record["id"]] = record
    return record


def find(collection, record_id):
    if not record_id:
        return None
    return coll(collection).get(record_id)


def all_of(collection):
    return list(coll(collection).values())


def by_created(items):
    """Ascending creation order (created_at, then insertion sequence)."""
    return sorted(items, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
