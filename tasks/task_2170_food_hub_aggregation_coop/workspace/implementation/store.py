"""In-memory data store and the logical hub clock.

Storage is process-local Python dicts keyed by id.  Nothing is persisted to
disk, so a fresh process starts with a completely empty store — no entity data
is ever seeded, preloaded or hardcoded at import or startup time.
"""

import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.5: at startup the logical clock reads exactly 2026-08-01T00:00:00Z.
STARTUP_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_COLLECTIONS = (
    "producers", "documents", "products", "buyers", "orders", "lines",
    "allocations", "dock_slots", "appointments", "routes", "claims", "cycles",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = STARTUP_CLOCK
        for name in _COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
request_lock = threading.RLock()


# ---------------------------------------------------------------------------
# clock helpers
# ---------------------------------------------------------------------------

def now():
    """The current logical clock instant.  Never wall-clock time."""
    return db.clock


def set_clock(instant):
    db.clock = instant


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (value.microsecond // 1000)) + "Z"


def add_days(instant, days):
    return instant + timedelta(days=days)


def add_minutes(instant, minutes):
    return instant + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# identity / common fields
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def base_record(extra=None):
    """Every entity carries id, created_at, updated_at and version."""
    instant = now()
    rec = {
        "id": new_id(),
        "created_at": instant,
        "updated_at": instant,
        "version": 1,
        "_seq": db.next_seq(),
    }
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """Refresh updated_at and increment version by exactly 1.

    PRD 2.10: each record a cascade touches has its updated_at refreshed and
    its version incremented by 1 — once per request, however many hops of the
    same cascade reach it.
    """
    from flask import g
    try:
        seen = g._touched
    except (AttributeError, RuntimeError):
        seen = None
    rec["updated_at"] = now()
    if seen is None:
        rec["version"] += 1
        return
    if rec["id"] in seen:
        return
    seen.add(rec["id"])
    rec["version"] += 1


def sorted_records(records):
    """Default list ordering: created_at ascending, stable by insertion order."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# integer money helpers (PRD 2.6)
# ---------------------------------------------------------------------------

def round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) for non-negative integer inputs."""
    if denominator == 0:
        return 0
    if numerator < 0:
        return -((2 * (-numerator) + denominator) // (2 * denominator))
    return (2 * numerator + denominator) // (2 * denominator)


def apply_bp(amount_cents, bp):
    """amount * bp / 10000, rounded half up to a whole cent."""
    return round_half_up_div(amount_cents * bp, 10000)


def ceil_div(numerator, denominator):
    if denominator <= 0:
        return 0
    return -((-numerator) // denominator)
