"""In-memory data store, logical clock and common-field helpers.

Storage is process-local only: every re-invocation of start.sh begins with a
completely empty store.  No business entity is ever seeded here.
"""

import datetime
import itertools
import uuid
from decimal import Decimal

from flask import g

# ---------------------------------------------------------------------------
# collections
# ---------------------------------------------------------------------------
growers = {}
fields = {}
practice_history = {}
practice_standards = {}
enrollments = {}
baselines = {}
data_packets = {}
quantification_runs = {}
verification_bodies = {}
verifications = {}
credit_batches = {}
buffer_accounts = {}
reversal_events = {}
grower_payments = {}

_seq = itertools.count(1)
_req_seq = itertools.count(1)

# ---------------------------------------------------------------------------
# logical UTC clock (never reads the host wall clock)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"

clock = {
    "raw": CLOCK_DEFAULT_RAW,
    "dt": datetime.datetime(2026, 8, 1, 0, 0, 0),
}


def set_clock(raw, dt):
    clock["raw"] = raw
    clock["dt"] = dt


def now_raw():
    """The logical clock instant exactly as it was supplied/initialised."""
    return clock["raw"]


def now_dt():
    return clock["dt"]


def now_ts():
    """Logical clock rendered as ISO 8601 UTC with three fractional digits."""
    return fmt_instant(clock["dt"])


def fmt_instant(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def current_crop_year():
    return clock["dt"].year


# ---------------------------------------------------------------------------
# identifiers, common fields, mutation bookkeeping
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def new_request_id():
    return "req_" + uuid.uuid4().hex


def begin_request():
    g.mutation_token = next(_req_seq)


def _token():
    try:
        return g.mutation_token
    except Exception:
        return 0


def common_fields():
    ts = now_ts()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(row):
    """Register a mutation on ``row``.

    ``updated_at`` is refreshed and ``version`` increments by exactly one for
    the request that mutated the row -- including cascade-driven aggregate
    changes.  A row touched several times inside one request advances by one.
    """
    if row is None or "version" not in row:
        return row
    tok = _token()
    if row.get("_touched_by") == tok and tok != 0:
        return row
    row["_touched_by"] = tok
    row["version"] = row["version"] + 1
    row["updated_at"] = now_ts()
    return row


# ---------------------------------------------------------------------------
# buffer pool -- a required singleton ledger row, not test data
# ---------------------------------------------------------------------------
BUFFER_POOL_CODE = "PROGRAM_BUFFER"
MIN_RESERVE_RATIO = Decimal("0.05")


def buffer_pool():
    for row in buffer_accounts.values():
        if row["pool_code"] == BUFFER_POOL_CODE:
            return row
    return _init_buffer_pool()


def _init_buffer_pool():
    row = common_fields()
    row.update(
        {
            "pool_code": BUFFER_POOL_CODE,
            "balance_credits": 0,
            "contributed_total": 0,
            "drawn_total": 0,
            "released_total": 0,
            "unbacked_reversal_credits": 0,
            "outstanding_issued_credits": 0,
            "min_reserve_ratio": MIN_RESERVE_RATIO,
            "required_reserve_credits": 0,
            "next_serial_number": 1,
            "pool_status": "HEALTHY",
        }
    )
    buffer_accounts[row["id"]] = row
    return row


def sorted_rows(collection):
    return sorted(collection.values(), key=lambda r: r.get("_seq", 0))
