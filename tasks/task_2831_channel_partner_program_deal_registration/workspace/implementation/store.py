"""In-memory store, logical clock, and request-level snapshot/rollback.

Storage is process-local Python dicts only. Nothing is persisted to disk, and
every fresh process starts with a completely empty store.
"""
import copy
import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: before the first /_clock/set_current_utc call the logical clock reads
# exactly 2026-08-01T00:00:00Z, and it never falls back to real wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "partners",
    "certifications",
    "accounts",
    "mappings",
    "registrations",
    "conflicts",
    "sprs",
    "allocations",
    "claims",
    "proofs",
    "orders",
    "reviews",
)

DB = {}


def reset():
    DB.clear()
    for name in COLLECTIONS:
        DB[name] = {}
    DB["_clock"] = CLOCK_DEFAULT
    DB["_seq"] = 0


reset()


def col(name):
    return DB[name]


def now():
    return DB["_clock"]


def set_clock(instant):
    DB["_clock"] = instant


def next_seq():
    DB["_seq"] = DB["_seq"] + 1
    return DB["_seq"]


def new_id():
    return str(uuid.uuid4())


def insert(collection, row):
    instant = now()
    row["id"] = new_id()
    row["created_at"] = instant
    row["updated_at"] = instant
    row["version"] = 1
    row["_seq"] = next_seq()
    DB[collection][row["id"]] = row
    return row


def touch(row):
    """Bump a row's version and refresh updated_at (PRD 2.4 / 2.9)."""
    row["version"] = row["version"] + 1
    row["updated_at"] = now()
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[collection].get(row_id)


def all_rows(collection):
    """Every row of a collection in insertion order."""
    return sorted(DB[collection].values(), key=lambda r: r["_seq"])


def ordered(rows):
    """Default list ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# transaction support: a cascade is atomic with the request that triggered it
# --------------------------------------------------------------------------
def snapshot():
    return copy.deepcopy(DB)


def restore(snap):
    DB.clear()
    DB.update(snap)


# --------------------------------------------------------------------------
# datetime helpers
# --------------------------------------------------------------------------
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|\+00:00|\+0000)$"
)


def parse_instant(value):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac = (
        int(m.group(1)), int(m.group(2)), int(m.group(3)),
        int(m.group(4)), int(m.group(5)), int(m.group(6)), m.group(7),
    )
    micros = 0
    if frac:
        micros = int((frac + "000000")[:6])
    try:
        return datetime(year, month, day, hour, minute, second, micros,
                        tzinfo=timezone.utc)
    except ValueError:
        return None


def fmt_instant(value):
    if value is None:
        return None
    millis = value.microsecond // 1000
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), millis)


def plus_days(instant, days):
    """PRD 2.6: adding days is an exact multiple of twenty-four hours."""
    return instant + timedelta(days=days)
