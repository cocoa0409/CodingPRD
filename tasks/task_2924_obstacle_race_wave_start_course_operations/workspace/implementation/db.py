"""In-memory store, the logical race clock, and row bookkeeping.

The store is a plain dict of dicts keyed by id.  It starts EMPTY on every boot:
nothing is seeded, preloaded or hardcoded -- every row is created through the
declared API surface.
"""

import copy
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5): the server never reads wall-clock time.
# ---------------------------------------------------------------------------

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {
    "clock": CLOCK_EPOCH,
    "seq": 0,
}

COLLECTIONS = (
    "venues",
    "permits",
    "courses",
    "obstacles",
    "divisions",
    "waves",
    "participants",
    "entries",
    "attempts",
    "staff_assignments",
    "festival_services",
    "restoration_tasks",
)

STORE = {name: {} for name in COLLECTIONS}


def reset():
    for name in COLLECTIONS:
        STORE[name] = {}
    _state["clock"] = CLOCK_EPOCH
    _state["seq"] = 0


def now():
    """The current logical clock value."""
    return _state["clock"]


def set_clock(value):
    _state["clock"] = value


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Timestamp formatting (PRD 2.4): ISO 8601 UTC, exactly three fractional digits.
# ---------------------------------------------------------------------------


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def plus_seconds(dt, seconds):
    return dt + timedelta(seconds=int(seconds))


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=int(minutes))


def seconds_between(start, end):
    """Exact whole-second difference; never rounded (PRD 2.9)."""
    return int((end - start).total_seconds())


# ---------------------------------------------------------------------------
# Row creation / mutation bookkeeping
# ---------------------------------------------------------------------------


def insert(collection, row, versioned=True):
    """Store a freshly built row, stamping id / created_at / version."""
    row["id"] = new_id()
    created = now()
    row["created_at"] = created
    if versioned:
        row["updated_at"] = created
        row["version"] = 1
    row["_seq"] = next_seq()
    STORE[collection][row["id"]] = row
    return row


def bump(row):
    """Advance version and refresh updated_at in the same operation (PRD 2.4)."""
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = now()


def _snapshot(row):
    return {
        k: copy.deepcopy(v)
        for k, v in row.items()
        if not k.startswith("_") and k not in ("version", "updated_at")
    }


@contextmanager
def mutation(row):
    """Bump version/updated_at only when the row actually changed."""
    before = _snapshot(row)
    yield row
    if _snapshot(row) != before:
        bump(row)


@contextmanager
def forced_mutation(row):
    """Bump version/updated_at unconditionally (PRD says 'version increments')."""
    yield row
    bump(row)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return STORE[collection].get(row_id)


def all_rows(collection):
    """Every row of a collection in creation order."""
    return sorted(STORE[collection].values(), key=lambda r: r["_seq"])


def where(collection, **filters):
    rows = []
    for row in all_rows(collection):
        if all(row.get(k) == v for k, v in filters.items()):
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _value(v):
    if isinstance(v, datetime):
        return iso(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return [_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _value(x) for k, x in v.items()}
    return v


def serialize(row):
    """Public representation: internal keys (leading underscore) are dropped."""
    if row is None:
        return None
    return {k: _value(v) for k, v in row.items() if not k.startswith("_")}


def serialize_many(rows):
    return [serialize(r) for r in rows]
