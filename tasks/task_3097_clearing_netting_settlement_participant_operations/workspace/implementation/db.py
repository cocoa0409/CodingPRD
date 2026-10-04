"""In-memory data store.

The store is deliberately process-local and starts empty on every boot: no
seeding, no preloading, no persistence. start.sh re-invocation therefore wipes
every byte of state, which is what the per-test-server isolation mode requires.
"""

import threading
import time
import uuid
from datetime import datetime, timezone

# PRD 2.7: the logical clock's startup default is exactly this instant and the
# server never falls back to host wall-clock time for deadline evaluation.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

TABLES = (
    "participants",
    "deposits",
    "deposit_transactions",
    "securities",
    "custody_accounts",
    "settlement_windows",
    "net_positions",
    "trade_submissions",
    "corporate_actions",
    "clearing_funds",
    "fund_components",
    "default_proceedings",
    "loss_allocations",
    "bids",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._event_seq = 0
        self._last_ms = 0

    # -- identifiers --------------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    # -- logical clock ------------------------------------------------------
    def get_clock(self):
        return self.clock

    def set_clock(self, iso):
        self.clock = iso

    # -- monotone timestamps ------------------------------------------------
    def now_iso(self):
        """A strictly increasing ISO 8601 UTC instant with 3 fractional digits.

        Strict monotonicity keeps ``created_at ASC`` ordering deterministic even
        when several resources are minted inside the same millisecond.
        """
        ms = int(time.time() * 1000)
        if ms <= self._last_ms:
            ms = self._last_ms + 1
        self._last_ms = ms
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (ms % 1000)

    # -- event ordering -----------------------------------------------------
    def next_event_seq(self):
        self._event_seq += 1
        return self._event_seq


db = Store()


def touch(record):
    """Refresh the common-field quartet on an ordinary resource."""
    record["updated_at"] = db.now_iso()
    record["version"] = record.get("version", 0) + 1
    return record


def new_record(**fields):
    """Mint an ordinary resource carrying the common field set (PRD 2.10)."""
    rec = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": None,
        "version": 1,
    }
    rec.update(fields)
    rec["updated_at"] = rec["created_at"]
    return rec


def new_ledger_row(**fields):
    """Mint an append-only ledger row: only id and created_at."""
    rec = {"id": db.new_id(), "created_at": db.now_iso()}
    rec.update(fields)
    return rec