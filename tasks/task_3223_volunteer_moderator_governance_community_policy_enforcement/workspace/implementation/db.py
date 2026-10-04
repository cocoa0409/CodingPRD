"""In-memory data store, logical clock and generic entity helpers.

Storage is Python dicts only. Nothing is written to disk, nothing is cached in
/tmp, and no entity data is registered at import time: the store is born empty
every time start.sh launches a fresh process.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import fail

# --------------------------------------------------------------------------
# Logical clock (§2.4). Startup default is exactly 2026-09-01T00:00:00Z; it
# never falls back to wall-clock time.
# --------------------------------------------------------------------------
_DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"current_utc": _DEFAULT_CLOCK}


def now():
    return _clock["current_utc"]


def set_clock(value):
    _clock["current_utc"] = value
    return _clock["current_utc"]


def clock_value():
    return _clock["current_utc"]


def reset_clock():
    _clock["current_utc"] = _DEFAULT_CLOCK


# --------------------------------------------------------------------------
# Store: one dict per entity kind, each keyed by id. Born empty.
# --------------------------------------------------------------------------
# Time-driven automatic transitions are swept once per distinct clock value.
settle = {"clock": None}

STATUS = {
    "Community": {},
    "CommunityRule": {},
    "Moderator": {},
    "TeamSuccession": {},
    "Post": {},
    "Account": {},
    "ContentReport": {},
    "AutoDetectionBacklogItem": {},
    "ContentDecision": {},
    "AccountSanction": {},
    "BrigadingCluster": {},
    "Appeal": {},
    "ProtestEvent": {},
    "ProtestApproval": {},
    # side tables (not entities)
    "EscalationRecord": {},
    "ModerationAction": {},
    "RegulationCadence": {},
}


def reset():
    """Wipe every byte of state — used by the store's own reset capability."""
    for bucket in STATUS.values():
        bucket.clear()
    reset_clock()
    settle["clock"] = None


def bucket(kind):
    return STATUS[kind]


# --------------------------------------------------------------------------
# Timestamps and identifiers
# --------------------------------------------------------------------------
def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "current_utc is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    """A plain UUID, no type prefix and no encoding of the entity kind."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex.upper()[:18]


DAYS = lambda n: timedelta(days=n)  # noqa: E731


def advance(dt, days):
    return dt + timedelta(days=days)


def days_between(earlier, later):
    """Whole number of days between two instants."""
    if earlier is None or later is None:
        return 0
    return (later - earlier).days


def at_least_days(anchor, days, reference=None):
    """True when at least `days` have elapsed between anchor and the clock."""
    if anchor is None:
        return False
    return (reference or now()) - anchor >= timedelta(days=days)


# --------------------------------------------------------------------------
# Numeric rounding (§2.8): two decimal places, round half up.
# --------------------------------------------------------------------------
TWO_DP = Decimal("0.01")
ZERO = Decimal("0.00")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round2(value):
    """round_half_up to two decimal places, returned as a Decimal."""
    return dec(value).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def num(value):
    """Expose a stored Decimal as a JSON number with two decimal places."""
    if value is None:
        return None
    return float(round2(value))


def round_half_up_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Generic record lifecycle
# --------------------------------------------------------------------------
def stamp_created(record):
    stamp = iso(now())
    record["id"] = new_id()
    record["created_at"] = stamp
    record["updated_at"] = stamp
    record["version"] = 1


def touch(record):
    """Refresh updated_at and advance version by one."""
    record["updated_at"] = iso(now())
    record["version"] = record.get("version", 1) + 1


def insert(kind, record):
    stamp_created(record)
    STATUS[kind][record["id"]] = record
    return record


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
def find(kind, record_id):
    if record_id is None:
        return None
    return STATUS[kind].get(record_id)


def load(kind, record_id, error_id="ERR_NOT_FOUND"):
    record = find(kind, record_id)
    if record is None:
        fail(error_id)
    return record


def children(kind, parent_key, parent_id):
    return [r for r in STATUS[kind].values() if r.get(parent_key) == parent_id]


def all_of(kind):
    return list(STATUS[kind].values())


def sorted_created(records):
    """Every list endpoint returns creation-timestamp ascending (§2.3)."""
    return sorted(records, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))