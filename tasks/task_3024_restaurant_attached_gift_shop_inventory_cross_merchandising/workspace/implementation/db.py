"""In-memory data store, logical clock and common-field bookkeeping.

Storage is process memory only: plain dicts keyed by the server-minted id.
Nothing is written to disk, nothing is cached in /tmp, and there is no seed
data of any kind — the store starts empty on every boot and every entity a
test needs is constructed through the declared API surface.

Internal bookkeeping keys are prefixed with "_" and are stripped before any
record is serialized, so no field that does not trace to the PRD ever leaves
the server.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from errors import ApiError

# ---------------------------------------------------------------------------
# Entity tables
# ---------------------------------------------------------------------------

brands = {}
locations = {}
store_days = {}
items = {}
planogram_versions = {}
planogram_slots = {}
guest_checks = {}
receipts = {}
clearance_schedules = {}
staff_shifts = {}
transfers = {}
capacity_readings = {}

# Monotonic insertion counter.  PRD 2.3 orders list results by created_at
# ascending and leaves ties unspecified; this counter keeps our own ordering
# deterministic without perturbing any timestamp.
_order = {"n": 0}


def next_order():
    _order["n"] += 1
    return _order["n"]


# ---------------------------------------------------------------------------
# Logical clock — PRD 2.4: starts at exactly 2026-09-01T00:00:00Z and advances
# only through the clock-setting capability or the store-day advance capability.
# ---------------------------------------------------------------------------

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0)

_clock = {"t": CLOCK_START}


def now():
    """The logical clock's current instant (naive UTC)."""
    return _clock["t"]


def set_clock(dt):
    _clock["t"] = dt


def current_utc_str():
    return fmt_ts(_clock["t"])


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(value, field="timestamp"):
    """Parse an ISO 8601 instant into a naive UTC datetime."""
    if value is None:
        raise ApiError("ERR_INVALID_REQUEST", "Required ISO 8601 field %s is missing." % field)
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "Malformed ISO 8601 timestamp: %s" % value)
    else:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed ISO 8601 timestamp.")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def plus_days(dt, days):
    return dt + timedelta(days=days)


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Common fields — PRD 2.4: id, created_at, updated_at, version on all twelve.
# ---------------------------------------------------------------------------

def mint_id():
    return str(uuid.uuid4())


def new_record(payload):
    rec = dict(payload)
    rec["id"] = mint_id()
    rec["created_at"] = fmt_ts(now())
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_order"] = next_order()
    return rec


def touch(rec):
    """Bump a resource exactly as a direct client write would (PRD 2.8)."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = fmt_ts(now())
    return rec


# ---------------------------------------------------------------------------
# Money / rounding helpers — PRD 2.5.
# ---------------------------------------------------------------------------

CENT = Decimal("0.01")


def to_dec(value, default=Decimal(0)):
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    return Decimal(str(value))


def cents(value):
    """Round to whole cents, half up."""
    return int(to_dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def two_dp(value):
    return to_dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def four_dp(value):
    return to_dec(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def pct4(value):
    """Percentage-valued output: 4 decimals, half up, returned as a float."""
    return float(four_dp(value))


def floor_int(value):
    return int(to_dec(value).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def get_or_404(table, entity_id, error_id):
    rec = table.get(entity_id) if entity_id is not None else None
    if rec is None:
        raise ApiError(error_id)
    return rec