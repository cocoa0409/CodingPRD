"""In-memory data store, logical clock, and common-field helpers.

Storage is process-local only: every re-invocation of start.sh begins with a
completely empty store. No business entity is seeded here.
"""

import datetime
import itertools
import uuid

from flask import g

# ---------------------------------------------------------------------------
# collections
# ---------------------------------------------------------------------------
facilities = {}
dough_types = {}
cafes = {}
demand_adjustments = {}
cafe_orders = {}
production_plans = {}
delivery_routes = {}
route_stops = {}
cafe_schedules = {}
bake_entries = {}
donation_pickups = {}
billing_periods = {}
settlement_lines = {}
invoices = {}          # order_id -> invoice_total_cents

_seq = itertools.count(1)
_req_seq = itertools.count(1)

# ---------------------------------------------------------------------------
# logical UTC clock (never reads the host wall clock)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT_RAW = "2026-09-01T00:00:00Z"

clock = {
    "raw": CLOCK_DEFAULT_RAW,
    "dt": datetime.datetime(2026, 9, 1, 0, 0, 0),
}


def set_clock(raw, dt):
    clock["raw"] = raw
    clock["dt"] = dt


def now_raw():
    return clock["raw"]


def now_dt():
    return clock["dt"]


def now_ts():
    """Logical clock rendered as ISO 8601 UTC with three fractional digits."""
    return fmt_instant(clock["dt"])


def fmt_instant(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


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
    """Register a mutation on ``row``: version +1, updated_at refreshed.

    A row touched several times inside one request advances by exactly one.
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


def sorted_rows(collection):
    return sorted(collection.values(), key=lambda r: r.get("_seq", 0))
