"""In-memory data store and the server-side logical clock (PRD §2.11).

Storage is process memory only: every dict below starts empty on every boot and
NOTHING is seeded, preloaded or hardcoded.  Re-invoking start.sh wipes all state.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

# The logical clock reads exactly 2026-08-01T00:00:00Z before any client sets it,
# and never falls back to the machine's wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOCK = threading.RLock()


class Store:
    """All collections keyed by id.  Insertion order is preserved by dict."""

    def __init__(self):
        self.program_tiers = {}
        self.distributors = {}
        self.members = {}
        self.letters = {}
        self.deals = {}
        self.items = {}
        self.rate_cards = {}
        self.batches = {}
        self.lines = {}
        self.accruals = {}
        self.claims = {}
        self.disputes = {}
        self.reviews = {}
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def now_iso(self):
        return iso_instant(self.clock)


db = Store()


def new_id():
    return str(uuid.uuid4())


def iso_instant(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def new_record(kind, fields):
    """Create a record carrying id/created_at/updated_at/version (PRD §2.4)."""
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = db.now_iso()
    rec["updated_at"] = db.now_iso()
    rec["version"] = 1
    rec["_kind"] = kind
    rec["_seq"] = db.next_seq()
    return rec


def new_immutable_record(kind, fields):
    """ComplianceReview carries id and created_at only (PRD §2.4)."""
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = db.now_iso()
    rec["_kind"] = kind
    rec["_seq"] = db.next_seq()
    return rec


# --------------------------------------------------------------------------
# Version / updated_at discipline (PRD §2.4)
#
# `version` starts at 1 and increases by exactly 1 on every mutation of the
# record, whether requested directly or produced as a downstream consequence.
# A single request that changes a record (however many of its fields or hops
# touch it) advances that record's version by exactly one step -- the PRD states
# this explicitly for the rate-card supersede case ("once per call, not once per
# card touched") and it is applied uniformly here.
# --------------------------------------------------------------------------

def begin_request():
    global _touched
    _touched = set()


_touched = set()


def touch(rec):
    """Mark a record mutated: bump version once per request and refresh updated_at."""
    if rec is None:
        return
    key = id(rec)
    if key in _touched:
        rec["updated_at"] = db.now_iso()
        return
    _touched.add(key)
    if "version" in rec:
        rec["version"] = rec["version"] + 1
    if "updated_at" in rec:
        rec["updated_at"] = db.now_iso()


# --------------------------------------------------------------------------
# ordering helpers
# --------------------------------------------------------------------------

def sort_desc(records):
    """Default list ordering: created_at descending (newest first).

    Because created_at is the logical-clock instant, several records created
    without moving the clock share it exactly; the monotonic insertion sequence
    breaks the tie so that "newest first" stays deterministic.
    """
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)


def sort_asc(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# date / instant helpers
# --------------------------------------------------------------------------

def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def date_of_instant(s):
    return s[:10]


def add_days(datestr, days):
    return (parse_date(datestr) + timedelta(days=days)).strftime("%Y-%m-%d")


def days_between(a, b):
    return (parse_date(b) - parse_date(a)).days


def parse_instant(s):
    """Parse an ISO 8601 UTC instant string into an aware datetime."""
    txt = s
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
