"""In-memory data store, logical clock, id / timestamp helpers.

The store is EMPTY on every boot.  No entity is ever seeded here.
"""

import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------
TABLES = (
    "customers",
    "assets",
    "standards",
    "benches",
    "core_units",
    "orders",
    "inspections",
    "measurements",
    "part_lines",
    "readings",
    "reservations",
    "installations",
    "claims",
    "credit_notes",
)

db = {name: {} for name in TABLES}

_seq = itertools.count(1)

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}


def reset():
    for name in TABLES:
        db[name] = {}
    _clock["now"] = CLOCK_DEFAULT


# ---------------------------------------------------------------------------
# ids / time
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def fmt_ts(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def real_now_iso():
    return fmt_ts(datetime.now(timezone.utc))


def logical_now():
    return _clock["now"]


def logical_now_iso():
    return fmt_ts(_clock["now"])


def set_logical(dt):
    _clock["now"] = dt


def parse_iso(value):
    """Parse an ISO-8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# record helpers
# ---------------------------------------------------------------------------
def base_record(with_version=True):
    rec = {
        "id": new_id(),
        "created_at": real_now_iso(),
        "_seq": next_seq(),
    }
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version by exactly 1."""
    rec["updated_at"] = real_now_iso()
    rec["version"] = rec.get("version", 0) + 1


def insert(table, rec):
    db[table][rec["id"]] = rec
    return rec


def get(table, rid):
    if not isinstance(rid, str):
        return None
    return db[table].get(rid)


def all_rows(table):
    return list(db[table].values())


def sorted_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------
def _scrub(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def public(rec, fields):
    """Project a record onto its declared public field list."""
    out = {}
    for name in fields:
        out[name] = _scrub(rec.get(name))
    return out


HOUR = timedelta(hours=1)
