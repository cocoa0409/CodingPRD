"""In-memory data store.

Every collection is a plain dict keyed by the server-minted UUID id.  The
store starts empty on every boot; nothing is ever seeded, preloaded or
hardcoded here.  Tests build every precondition through the declared API.
"""

import threading
import uuid
from datetime import datetime, timezone

# One global lock serialises request handling so cascades stay atomic.
LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.plans = {}
        self.participants = {}
        self.valuations = {}
        self.loans = {}
        self.loan_payments = {}
        self.allocation_runs = {}
        self.share_allocations = {}
        self.forfeiture_events = {}
        self.distribution_elections = {}
        self.installment_payments = {}
        self.put_option_exercises = {}
        self.participant_statements = {}
        self._seq = 0
        self._last_ts = ""

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()

_TS_LOCK = threading.Lock()


def _format(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    """Strictly increasing ISO 8601 UTC stamp with three fractional digits.

    List ordering is by created_at ascending everywhere, so two rows written
    inside the same millisecond must still be separable.
    """
    with _TS_LOCK:
        stamp = _format(datetime.now(timezone.utc))
        if stamp <= DB._last_ts:
            # bump the previous stamp by one millisecond
            prev = datetime.strptime(DB._last_ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            from datetime import timedelta
            stamp = _format(prev + timedelta(milliseconds=1))
        DB._last_ts = stamp
        return stamp


def new_id():
    return str(uuid.uuid4())


def insert(collection, record, common_fields=True):
    """Assign identity/audit columns and store the record."""
    stamp = now_iso()
    row = {"id": new_id()}
    row.update(record)
    row["created_at"] = stamp
    if common_fields:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = DB.next_seq()
    collection[row["id"]] = row
    return row


def touch(row):
    """Every mutation of a resource bumps its version by exactly 1."""
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = now_iso()
    return row


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sorted_rows(collection):
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))
