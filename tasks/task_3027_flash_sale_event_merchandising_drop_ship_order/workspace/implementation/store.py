"""In-memory data store.

Storage is *in-memory only*: plain dicts keyed by id.  Nothing is seeded,
preloaded or persisted; every entity is built by a caller through the declared
API surface.  Because the process is re-launched per test by ``start.sh``, the
store is empty at every boot.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# The logical clock's startup default.  The server never falls back to the
# host's wall clock for clock-relative rules (PRD §2.11).
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "vendors",
    "shops",
    "events",
    "listings",
    "customers",
    "orders",
    "confirmations",
    "purchase_orders",
    "polines",
    "shipments",
    "parcels",
    "returns",
    "ledger",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        # idempotency_key -> ledger row id
        self.idem = {}
        # return id -> escalation count
        self.escalations = {}
        # chronological sequence stamps, so created_at ordering is total
        self.seq = 0

    def reset(self):
        for name in COLLECTIONS:
            getattr(self, name).clear()
        self.clock = DEFAULT_CLOCK
        self.idem.clear()
        self.escalations.clear()
        self.seq = 0


db = Store()


# --------------------------------------------------------------------------
# identifiers, clocks and versions
# --------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def now():
    """The logical clock instant."""
    return db.clock


def set_clock(value):
    db.clock = value


def tick():
    db.seq += 1
    return db.seq


def iso(dt):
    """ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_time(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def hours(n):
    return timedelta(hours=n)


def days(n):
    return timedelta(days=n)


# --------------------------------------------------------------------------
# numeric helpers (PRD §2.9)
# --------------------------------------------------------------------------

def rhu(value, places=0):
    """Round half up to ``places`` decimal places."""
    quant = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def rhu_rate(value):
    """A 4-decimal rate as a JSON number (or None)."""
    if value is None:
        return None
    return float(rhu(value, 4))


# --------------------------------------------------------------------------
# entity scaffolding
# --------------------------------------------------------------------------

def stamp(entity, with_version=True):
    """Apply the common fields to a freshly created entity."""
    entity["id"] = new_id()
    entity["created_at"] = now()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = tick()
    return entity


def touch(entity):
    """A mutation: refresh updated_at and bump version (PRD §2.4)."""
    entity["updated_at"] = now()
    entity["version"] = int(entity.get("version", 1)) + 1
    return entity


def clone(obj):
    """Shallow copy of a stored record for mutation."""
    return dict(obj)


def ordered(records):
    """Default list ordering: created_at ascending, creation order as tiebreak."""
    return sorted(records, key=lambda r: (r.get("created_at"), r.get("_seq", 0)))


def find(collection, ident):
    return getattr(db, collection).get(ident)


def put(collection, entity):
    getattr(db, collection)[entity["id"]] = entity
    return entity