"""In-memory data store, logical clock, and shared primitives.

The store is EMPTY on every boot: no seeding, no preloading, no persistence.
Every entity is created by callers through the declared endpoints.
"""

import itertools
import random
import re
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction

# --------------------------------------------------------------------------
# Global constants (PRD 2.9)
# --------------------------------------------------------------------------
MINIMUM_ORDER_CENTS = 1000
FREE_DELIVERY_THRESHOLD_CENTS = 10000
LOYALTY_TIER_THRESHOLD_CENTS = 5000
SURGE_FLOOR = Decimal("1.00")
SURGE_CEILING = Decimal("1.80")
MAINTENANCE_BUFFER_MINUTES = 15
PROPOSAL_TTL_MINUTES = 120
ACCURACY_HOLD_THRESHOLD = Decimal("0.9800")
ZONE_RANK = {"FROZEN": 0, "CHILLED": 1, "AMBIENT": 2}
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00.000Z"
GRAMS_PER_KG = 1000

TEMPERATURE_ZONES = ("AMBIENT", "CHILLED", "FROZEN")
ROLES = ("FulfillmentAdmin", "Customer", "WavePlanner", "PickOperator", "GridEngineer")

ALL_ROLES = list(ROLES)
STAFF_ROLES = ["FulfillmentAdmin", "WavePlanner", "PickOperator", "GridEngineer"]

# --------------------------------------------------------------------------
# Instant parsing / formatting  (ISO-8601 UTC, exactly 3 fractional digits out)
# --------------------------------------------------------------------------
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|z|\+00:00|\+0000)$"
)


def parse_instant(text):
    """Accept ...T00:00:00Z and ...T00:00:00.000Z (any fractional width)."""
    if not isinstance(text, str):
        return None
    m = _ISO_RE.match(text.strip())
    if not m:
        return None
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def fmt_instant(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now():
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Decimal helpers -- half up, away from zero
# --------------------------------------------------------------------------
def round_half_up(value, places=0):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def round_cents(value):
    return int(round_half_up(value, 0))


def fraction_to_decimal(fr, places):
    with localcontext() as ctx:
        ctx.prec = 60
        d = Decimal(fr.numerator) / Decimal(fr.denominator)
    return round_half_up(d, places)


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------
TABLES = (
    "routes", "bays", "zones", "stations", "skus", "windows", "slots",
    "accounts", "orders", "lines", "bookings", "waves", "totes", "tasks",
    "proposals",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self.clock = parse_instant(DEFAULT_CLOCK_UTC)

    def tables(self):
        return [getattr(self, name) for name in TABLES]

    def every_entity(self):
        for table in self.tables():
            for ent in table.values():
                yield ent


db = Store()
LOCK = threading.RLock()

_seq_counter = itertools.count(1)
_request_state = threading.local()


def next_seq():
    return next(_seq_counter)


def new_entity():
    now = wall_now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def created_key(ent):
    return (ent["created_at"], ent["_seq"])


def by_created(items):
    return sorted(items, key=created_key)


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# --------------------------------------------------------------------------
# Version bookkeeping.
#
# PRD 2.4: version increments by exactly 1 on every mutation of a resource and
# updated_at is refreshed. Explicitly enumerated bumps (CustomerOrder) are
# applied by hand through bump(); anything else that actually changed during
# the request is bumped once by finalize_versions().
# --------------------------------------------------------------------------
_SKIP_KEYS = ("version", "updated_at")


def _snapshot_entity(ent):
    return {k: v for k, v in ent.items() if k not in _SKIP_KEYS}


def begin_request():
    _request_state.snapshot = {
        ent["id"]: _snapshot_entity(ent) for ent in db.every_entity()
    }
    _request_state.bumped = set()


def bump(ent):
    """Explicit, enumerated version bump (idempotent within one request)."""
    bumped = getattr(_request_state, "bumped", None)
    if bumped is None:
        bumped = set()
        _request_state.bumped = bumped
    if ent["id"] in bumped:
        return
    bumped.add(ent["id"])
    ent["version"] += 1
    ent["updated_at"] = wall_now()


def finalize_versions():
    snapshot = getattr(_request_state, "snapshot", None)
    if snapshot is None:
        return
    bumped = getattr(_request_state, "bumped", set())
    now = wall_now()
    for ent in db.every_entity():
        before = snapshot.get(ent["id"])
        if before is None:
            continue  # created during this request: version stays 1
        if ent["id"] in bumped:
            continue
        if _snapshot_entity(ent) != before:
            ent["version"] += 1
            ent["updated_at"] = now
    _request_state.snapshot = None
    _request_state.bumped = set()


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------
def serialize(ent):
    out = {}
    for key, value in ent.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = fmt_instant(value)
        elif isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, list):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def insert(table, fields):
    ent = new_entity()
    ent.update(fields)
    table[ent["id"]] = ent
    return ent


def abort_request():
    """Drop request-scoped version bookkeeping without bumping anything.

    Every gate in PRD 2.8 is evaluated before any mutation, so a rejected
    request has nothing to roll back -- it must simply not bump a version.
    """
    _request_state.snapshot = None
    _request_state.bumped = set()
