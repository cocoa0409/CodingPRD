"""In-memory data store, logical clock, and common-field helpers.

The store starts completely empty on every boot -- nothing is seeded here.
"""
import math
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone

LOCK = threading.RLock()

# The logical clock (PRD 2.4): starts at exactly 2026-09-01T00:00:00Z and
# advances only via POST /_clock/set_current_utc. Never falls back to wall time.
CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Entity stores, keyed by id. Insertion order is creation order (used for the
# default "sorted by creation timestamp ascending" list ordering).
stations = {}
union_agreements = {}
vendors = {}
rfp_cycles = {}
rfp_proposals = {}
contracts = {}
layovers = {}
allocations = {}
transport_trips = {}
feedback = {}
audits = {}
invoices = {}

# Monotonic per-record ordering counter so created_at ties keep insertion order.
_seq = 0


def set_clock(dt):
    global CLOCK
    CLOCK = dt


def now_iso():
    return iso(CLOCK)


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + secrets.token_hex(8)


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2/2.7)."""
    s = dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000))
    return s + "Z"


def parse_dt(value, field):
    """Parse an ISO8601 datetime. Returns (datetime|None, error_message|None)."""
    from errors import ApiError

    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO8601 string" % field, 400)
    try:
        s = value.strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "%s is not a valid ISO8601 datetime" % field, 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_valid_date_str(value):
    """True if value is a valid YYYY-MM-DD calendar date."""
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def date_str_to_dt(value):
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def whole_nights(start_dt, end_dt):
    """Whole days between two instants, floor (contract_value nights)."""
    return math.floor((end_dt - start_dt).total_seconds() / 86400.0)


def whole_hours(start_dt, end_dt):
    """Whole hours between two instants, floor (rest_compliance span)."""
    return math.floor((end_dt - start_dt).total_seconds() / 3600.0)


def stamp_new(rec, common=True):
    rec["id"] = new_id()
    rec["_seq"] = _next_seq()
    rec["created_at"] = now_iso()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation stamp: refresh updated_at and bump version by exactly 1."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def settle_lazy():
    """Lazy settlement (PRD 2.4): contracts past end_date -> EXPIRED; trips past
    pickup_time still SCHEDULED -> MISSED. Called before any read/write."""
    for c in contracts.values():
        if c["status"] == "ACTIVE" and CLOCK > c["_end_date"]:
            c["status"] = "EXPIRED"
            touch(c)
    for t in transport_trips.values():
        if t["status"] == "SCHEDULED" and CLOCK > t["_pickup_time"]:
            t["status"] = "MISSED"
            touch(t)


def public(rec):
    """Strip internal underscore-prefixed fields before serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
