"""In-memory data store, logical clock and numeric helpers.

The store starts completely empty on every boot; no entity is ever seeded.
"""

import decimal
import itertools
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

decimal.getcontext().prec = 50

ANALYTES = [
    "ARSENIC",
    "CADMIUM",
    "COPPER",
    "LEAD",
    "MERCURY",
    "MOLYBDENUM",
    "NICKEL",
    "SELENIUM",
    "ZINC",
    "PFOS",
]

ROLES = [
    "FacilityOperator",
    "LabAnalyst",
    "ComplianceOfficer",
    "Agronomist",
    "Farmer",
    "PublicLiaison",
]

MG_KG_TO_LB_PER_DRY_TON = Decimal("0.002")
KG_PER_DRY_TON = Decimal("907.185")
HECTARES_PER_ACRE = Decimal("0.404686")
FUEL_ESCALATOR = Decimal("1.08")

# --- collections -----------------------------------------------------------

facilities = {}
limits = {}
batches = {}
sites = {}
agreements = {}
events = {}
outlets = {}
orders = {}
complaints = {}
reports = {}
lab_results = {}
haul_tickets = {}
ledger = {}

_seq_counter = itertools.count(1)

# --- logical clock ---------------------------------------------------------

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_EPOCH}


def now():
    return _clock["now"]


def set_clock(value):
    _clock["now"] = value


def now_iso():
    return iso(_clock["now"])


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_dt(text):
    """Parse an ISO 8601 timestamp; returns None when unparseable."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days(n):
    return timedelta(days=n)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


# --- numeric helpers -------------------------------------------------------


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rnd(value, places):
    if value is None:
        return None
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def r2(value):
    return rnd(value, 2)


def r3(value):
    return rnd(value, 3)


def r4(value):
    return rnd(value, 4)


def r1(value):
    return rnd(value, 1)


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def touch(record):
    """Refresh updated_at from the logical clock and bump version by 1."""
    record["updated_at"] = now_iso()
    record["version"] = record["version"] + 1


def new_record(extra=None):
    rec = {"id": new_id(), "created_at": now_iso(), "_seq": next_seq()}
    if extra:
        rec.update(extra)
    return rec


def public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def year_of(dt):
    return dt.year if dt is not None else None
