"""In-memory data store + logical clock. Storage is Python dicts keyed by id;
every start.sh re-invocation boots a fresh process with an empty store. No
seeding, no file persistence, no wall-clock fallback (PRD §2.4)."""

import uuid
from datetime import datetime, timezone

from constants import CLOCK_DEFAULT_UTC

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK = {"now": None}  # initialized at module bottom


def now():
    """Current logical-clock instant (timezone-aware UTC datetime)."""
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt


def parse_dt(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Accepts a trailing 'Z', explicit offsets, naive values (assumed UTC), and
    date-only strings (midnight UTC). Returns None when unparseable.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Serialize an aware UTC datetime as ISO 8601 with 3 fractional digits
    and a 'Z' suffix (PRD §2.5)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


# ---------------------------------------------------------------------------
# Entity stores — one dict per collection, keyed by entity id
# ---------------------------------------------------------------------------

STORE = {
    "jurisdictions": {},
    "substances": {},
    "formulations": {},
    "components": {},
    "clearances": {},
    "converters": {},
    "distributors": {},
    "authorizations": {},
    "cases": {},
    "agreements": {},
    "orders": {},
    "programs": {},
    "accruals": {},
    "phaseouts": {},
    "reports": {},
}

_SEQ = {"n": 0}


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.5)."""
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion sequence — stable tie-break for list ordering when
    several rows share a created_at (the logical clock need not move between
    creates)."""
    _SEQ["n"] += 1
    return _SEQ["n"]


def stamp_new(row, with_version=True):
    """Populate system fields on a freshly created row."""
    row["id"] = new_id()
    row["created_at"] = now()
    row["_seq"] = next_seq()
    if with_version:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation: refresh updated_at from the logical clock and bump
    version by one (PRD §2.5 — applies to cascade-driven mutations too)."""
    row["updated_at"] = now()
    row["version"] += 1


def sort_key(row):
    """Default list ordering: created_at ascending, insertion-sequence tie-break."""
    return (row["created_at"], row["_seq"])


# Initialize the logical clock to its pinned default.
_CLOCK["now"] = parse_dt(CLOCK_DEFAULT_UTC)
