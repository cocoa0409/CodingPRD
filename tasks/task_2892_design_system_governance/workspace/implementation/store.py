"""In-memory data store plus the server-held logical clock.

Storage is process-local and starts completely empty on every boot: no entity is
ever seeded, preloaded or hardcoded here. Every row is created by an API call.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self.teams = {}
        self.components = {}
        self.impls = {}
        self.deps = {}
        self.token_sets = {}
        self.tokens = {}
        self.proposals = {}
        self.reviews = {}
        self.releases = {}
        self.plans = {}
        self.audits = {}
        self.scans = {}
        self.grants = {}
        self._seq = 0

    # ---- clock -----------------------------------------------------------
    @property
    def now(self):
        return self.clock

    @property
    def now_iso(self):
        return iso(self.clock)

    # ---- identity / bookkeeping ------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_row(self, mutable=True):
        row = {
            "id": str(uuid.uuid4()),
            "created_at": self.now_iso,
            "_seq": self.next_seq(),
            "_created_dt": self.clock,
        }
        if mutable:
            row["updated_at"] = self.now_iso
            row["version"] = 1
        return row

    def touch(self, row, bump=True):
        row["updated_at"] = self.now_iso
        if bump and "version" in row:
            row["version"] = row["version"] + 1


store = Store()


def sort_created_asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more


def days_between(start_dt, end_dt):
    """Whole days from start to end, fractional part discarded."""
    seconds = (end_dt - start_dt).total_seconds()
    return int(seconds // 86400) if seconds >= 0 else -int((-seconds) // 86400)


__all__ = [
    "store", "Store", "iso", "sort_created_asc", "paginate", "days_between",
    "CLOCK_DEFAULT", "timedelta",
]
