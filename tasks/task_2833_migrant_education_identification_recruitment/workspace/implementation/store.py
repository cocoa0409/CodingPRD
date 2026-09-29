"""In-memory data store, the logical program clock, and version bookkeeping.

Storage is process-local and starts completely empty on every boot: no seeding,
no preloading, no on-disk persistence of any kind.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

from envelope import iso_from_epoch_ms

CLOCK_INITIAL = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.areas = {}
        self.recruiters = {}
        self.assignments = {}
        self.students = {}
        self.moves = {}
        self.interviews = {}
        self.coes = {}
        self.qc_reviews = {}
        self.terms = {}
        self.transfers = {}
        self.plans = {}
        self.deliveries = {}
        self.clock = CLOCK_INITIAL
        self._last_ms = 0

    # -- identity / time ---------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def now_iso(self):
        """Row stamp taken from the logical clock -- nothing here reads the wall clock.

        The stamp is the current logical clock instant, nudged forward by one
        millisecond whenever it would repeat or regress a stamp already issued, so
        that created_at remains a strict total order over serialised creates while
        the first row written after any clock move carries the clock instant exactly.
        """
        ms = int((self.clock - _EPOCH).total_seconds() * 1000)
        if ms <= self._last_ms:
            ms = self._last_ms + 1
        self._last_ms = ms
        return iso_from_epoch_ms(ms)

    # -- logical clock -----------------------------------------------------
    def clock_instant(self):
        dt = self.clock
        return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
            dt.microsecond // 1000,
        )

    def clock_date(self):
        return self.clock.date()


store = Store()


# --------------------------------------------------------------------------
# version / updated_at bookkeeping
# --------------------------------------------------------------------------

def _bumped_set():
    marker = getattr(g, "_bumped_rows", None)
    if marker is None:
        marker = set()
        g._bumped_rows = marker
    return marker


def mark_fresh(row):
    """A row created in this request never takes a version increment here."""
    _bumped_set().add(row["id"])


def bump(row, force=False):
    """One version increment per row per accepted request mutation."""
    seen = _bumped_set()
    if not force and row["id"] in seen:
        return False
    seen.add(row["id"])
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = store.now_iso()
    return True


def touch_only(row):
    """Refresh updated_at without advancing version."""
    if "updated_at" in row:
        row["updated_at"] = store.now_iso()


def base_row(with_version=True):
    created = store.now_iso()
    row = {"id": store.new_id(), "created_at": created}
    if with_version:
        row["updated_at"] = created
        row["version"] = 1
    return row


def sort_newest_first(rows):
    ordered = sorted(rows, key=lambda r: r["id"])
    ordered.sort(key=lambda r: r["created_at"], reverse=True)
    return ordered


def sort_oldest_first(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


UTC = timezone.utc
ONE_DAY = timedelta(days=1)
