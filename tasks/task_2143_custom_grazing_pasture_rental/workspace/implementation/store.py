"""In-memory data store, logical clock and record bookkeeping.

The store starts EMPTY on every boot.  Nothing is seeded here.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

from flask import g

# --------------------------------------------------------------------------
# Logical clock (PRD 2.7).  Before any operator has set it the clock reads
# exactly 2026-08-01T00:00:00Z and it never falls back to wall-clock time.
# --------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.graziers = {}
        self.cattle_owners = {}
        self.consultants = {}
        self.pastures = {}
        self.assessments = {}
        self.drought_readings = {}
        self.contracts = {}
        self.lots = {}
        self.weight_events = {}
        self.treatments = {}
        self.death_losses = {}
        self.tickets = {}
        self.settlements = {}
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def wall_now():
    return datetime.now(timezone.utc)


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (dt.microsecond // 1000)


def format_clock(dt):
    """Render a logical-clock instant.

    PRD 2.7 states the un-set clock reads exactly `2026-08-01T00:00:00Z`, so
    whole-second instants render without a fractional part; sub-second
    instants keep three fractional digits.
    """
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso_ms(dt)


def now_iso():
    return iso_ms(wall_now())


def new_record(common_fields=True):
    """Create a base record dict with identity / audit fields (PRD 2.4)."""
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
    }
    if common_fields:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Mutate audit fields once per request for this record (PRD 2.4 / 2.9)."""
    if rec is None:
        return
    if "version" not in rec:
        return
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    if id(rec) in touched:
        return
    touched.add(id(rec))
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now_iso()
