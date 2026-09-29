"""In-memory store, logical shop clock and record bookkeeping.

The store starts empty on every boot. Nothing is seeded, preloaded or
hardcoded; every record is created by a caller through a declared endpoint.
"""

import datetime as _dt
import random
import string
import uuid
from decimal import Decimal

# ---------------------------------------------------------------------------
# Logical shop clock (PRD 2.5). Nothing in this system reads wall-clock time.
# ---------------------------------------------------------------------------
CLOCK_EPOCH = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)
_clock = {"now": CLOCK_EPOCH}


def clock_now():
    return _clock["now"]


def clock_set(dt):
    _clock["now"] = dt


def clock_today():
    return _clock["now"].date()


def iso_instant(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    dt = dt.astimezone(_dt.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso_instant(clock_now())


def iso_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------
STORE_NAMES = (
    "personnel", "certificates", "audits", "jobs", "calculations", "heats",
    "parts", "wps", "qualifications", "welds", "exams", "nonconformances",
    "batches", "tests", "reports",
)

stores = {name: {} for name in STORE_NAMES}

_counter = {"seq": 0}


def _next_seq():
    _counter["seq"] += 1
    return _counter["seq"]


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def insert(store_name, fields, versioned=True):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = _next_seq()
    rec["_store"] = store_name
    stores[store_name][rec["id"]] = rec
    return rec


def get(store_name, rec_id):
    if not isinstance(rec_id, str):
        return None
    return stores[store_name].get(rec_id)


def all_of(store_name):
    """Every record of a store in canonical (created_at, insertion) order."""
    return sorted(stores[store_name].values(), key=lambda r: (r["created_at"], r["_seq"]))


def touch(rec):
    """Register one mutation of a record: new updated_at and version + 1."""
    if "version" in rec:
        rec["updated_at"] = now_iso()
        rec["version"] = rec["version"] + 1
    return rec


def mutate(rec, changes):
    """Apply changes; count as a mutation only when a stored value moves."""
    changed = False
    for key, value in changes.items():
        if key not in rec or not _same(rec.get(key), value):
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed


def _same(a, b):
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return a == b and a.as_tuple().exponent == b.as_tuple().exponent
    if type(a) is bool or type(b) is bool:
        return type(a) is type(b) and a == b
    return a == b


# ---------------------------------------------------------------------------
# Public serialisation: strips the internal bookkeeping keys.
# ---------------------------------------------------------------------------
_PRIVATE_PREFIX = "_"


def public(rec):
    if rec is None:
        return None
    out = {}
    for key, value in rec.items():
        if key.startswith(_PRIVATE_PREFIX):
            continue
        out[key] = value
    return out
