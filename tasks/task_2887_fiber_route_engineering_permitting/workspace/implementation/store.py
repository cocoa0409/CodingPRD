"""In-memory data store, logical clock and mutation bookkeeping.

Storage is process-local and volatile: every boot starts completely empty and
no entity is ever seeded, preloaded or hardcoded here.  Tests build all state
through the declared API surface.
"""

import uuid
from datetime import datetime, timedelta

from flask import g

# PRD section 2.5: the logical clock reads exactly this instant before any
# client has set it and never falls back to the host's wall clock.
LOGICAL_CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0)

INSTANT_FMT = "%Y-%m-%dT%H:%M:%SZ"


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.routes = {}
        self.segments = {}
        self.walkouts = {}
        self.observations = {}
        self.pole_apps = {}
        self.mr_items = {}
        self.permits = {}
        self.moratoria = {}
        self.designs = {}
        self.splice_points = {}
        self.as_builts = {}
        self.clock = LOGICAL_CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

def now_dt():
    return db.clock


def now_iso():
    return db.clock.strftime(INSTANT_FMT)


def to_iso(dt):
    if dt is None:
        return None
    return dt.strftime(INSTANT_FMT)


def set_clock(dt):
    db.clock = dt.replace(microsecond=0)
    return now_iso()


def plus_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def new_record(versioned=True):
    """Mint the common audit fields.

    Nine of the eleven resource types are versioned and carry
    id/created_at/updated_at/version.  PoleObservation and MakeReadyItem are
    append-only observations carrying only id and created_at -- updated_at and
    version are absent from their payloads entirely.
    """
    stamp = now_iso()
    rec = {
        "id": new_id(),
        "created_at": stamp,
        "_seq": db.next_seq(),
        "_versioned": versioned,
    }
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def _touched():
    if not hasattr(g, "touched_records"):
        g.touched_records = []
    return g.touched_records


def touch(rec):
    """Mark a versioned record as mutated by this request.

    Every record touched during a request -- whether by the direct write or by
    a cascade hop -- gets its updated_at refreshed and its version incremented
    by exactly 1, no matter how many hops reached it.  The bump lands
    immediately so that the record serialized into this request's own response
    already carries its new version.
    """
    if rec is None or not rec.get("_versioned"):
        return
    bucket = _touched()
    for existing in bucket:
        if existing is rec:
            return
    bucket.append(rec)
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now_iso()


def commit():
    g.touched_records = []


def sort_by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
