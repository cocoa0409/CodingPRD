"""In-memory data store and the logical clock.

Storage is process-local Python dicts only: every byte of state is discarded when
the process exits, so a fresh `start.sh` invocation starts with an entirely empty
system. Nothing is seeded, preloaded or hardcoded here — every row is created by
a client call to a declared endpoint.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.6: until the clock hook is first invoked the clock reads this instant.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

KINDS = (
    "municipalities",
    "accounts",
    "jobsites",
    "products",
    "crews",
    "quotes",
    "permits",
    "contracts",
    "work_orders",
    "invoices",
    "reconciliations",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        for kind in KINDS:
            setattr(self, kind, {})
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        self._last_ts = None

    # -- housekeeping ------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def wall_now(self):
        """Real-time UTC instant truncated to milliseconds, strictly increasing.

        created_at / updated_at are housekeeping stamps (PRD 2.4); making them
        strictly increasing keeps `created_at ASC` list ordering equal to
        creation order even for rows minted inside one request.
        """
        raw = datetime.now(timezone.utc)
        ts = raw.replace(microsecond=(raw.microsecond // 1000) * 1000)
        if self._last_ts is not None and ts <= self._last_ts:
            ts = self._last_ts + timedelta(milliseconds=1)
        self._last_ts = ts
        return ts

    def new_row(self, kind=None):
        """Mint the four housekeeping properties of PRD 2.4.

        `kind` names the collection the caller is about to file the row under; it
        is accepted for readability at the call sites and deliberately does not
        register the row, so a validation failure after this call leaves nothing
        behind in the store.
        """
        now = self.wall_now()
        return {
            "id": str(uuid.uuid4()),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": self.next_seq(),
        }

    def touch(self, row):
        """PRD 2.4: any mutation refreshes updated_at and bumps version by 1."""
        row["updated_at"] = self.wall_now()
        row["version"] += 1
        return row

    # -- lookups -----------------------------------------------------------
    def collection(self, kind):
        return getattr(self, kind)

    def sorted_rows(self, kind):
        rows = list(self.collection(kind).values())
        rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
        return rows


store = Store()
