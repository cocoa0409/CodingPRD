"""In-memory data store, logical clock and common-field helpers.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded here; every entity is created by clients through the declared
endpoints.
"""
import itertools
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# PRD §2.5 — before any operator moves it, the logical clock reads exactly this.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "schools",
    "supply_items",
    "grade_kit_specs",
    "kit_spec_lines",
    "drive_cycles",
    "collection_sites",
    "donation_batches",
    "inventory_positions",
    "cash_donations",
    "purchase_orders",
    "volunteer_events",
    "distribution_events",
    "student_registrations",
    "teacher_requests",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


# --------------------------------------------------------------------------
# Clock / time formatting
# --------------------------------------------------------------------------
def now():
    return db.clock


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso_real():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Common fields (PRD §2.4)
# --------------------------------------------------------------------------
def base_record():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    """Increment version by exactly 1 and refresh updated_at."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now()
    return rec


def serialize(rec):
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        out[key] = _ser_value(value)
    return out


def _ser_value(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_ser_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _ser_value(v) for k, v in value.items()}
    return value


def sort_records(records):
    """Default list ordering: created_at ascending (PRD §2.3), stable on ties."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# Numeric helpers
# --------------------------------------------------------------------------
def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def pct2(value):
    """Round a percentage half-up to exactly 2 decimals, returned as float."""
    return float(round_half_up(value, 2))
