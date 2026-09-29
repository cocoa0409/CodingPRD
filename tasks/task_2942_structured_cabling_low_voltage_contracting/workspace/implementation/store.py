"""In-memory store, the logical site clock (PRD 2.5) and exact-decimal helpers (PRD 2.6).

Nothing is seeded here: the store boots empty on every process start and every
entity is built by the caller through the declared API surface.
"""

import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# --------------------------------------------------------------------------
# PRD 2.5 — the logical site clock. Fixed origin, advanced only by
# POST /_clock/set_current_utc. The host wall clock is never read.
# --------------------------------------------------------------------------
CLOCK_ORIGIN = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.clock = CLOCK_ORIGIN
        self.seq = 0
        self.projects = {}
        self.rooms = {}
        self.racks = {}
        self.assignments = {}
        self.segments = {}
        self.cable_types = {}
        self.links = {}
        self.routes = {}
        self.test_results = {}
        self.registrations = {}
        self.tickets = {}
        self.coordinations = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()
lock = threading.RLock()


def now():
    """Current logical-clock reading."""
    return db.clock


def set_clock(dt):
    db.clock = dt
    return db.clock


def new_id():
    """Server-minted UUID string with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# --------------------------------------------------------------------------
# PRD 2.6 — exact decimal arithmetic, round half up. Never binary float.
# --------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("boolean is not a number")
    return Decimal(str(value))


def rnd(value, places):
    quant = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def r2(value):
    return rnd(value, 2)


def r4(value):
    return rnd(value, 4)


def rcents(value):
    """Round half up to whole cents and return an int (money is integer cents)."""
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def jsonable(value):
    """Recursively turn Decimals into JSON floats and datetimes into PRD timestamps."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, dict):
        return dict((k, jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


# --------------------------------------------------------------------------
# Common property set (PRD 2.4)
# --------------------------------------------------------------------------
def base_record(versioned=True):
    record = {"id": new_id(), "created_at": now()}
    if versioned:
        record["updated_at"] = now()
        record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """One mutation of a record: version += 1 and updated_at refreshed (PRD 2.4)."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now()
    return record


def ordered(records):
    """List ordering: created_at ascending, stable across pages (PRD 2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def minutes(count):
    return timedelta(minutes=count)
