"""In-memory data store, logical clock, and identity/timestamp helpers.

The store starts EMPTY on every boot (per-test-server isolation re-launches
the process before every test). No seeding of any entity is permitted here.
"""

import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Entity stores: name -> {id: entity-dict}
# ---------------------------------------------------------------------------
STORE = {
    "applicants": {},
    "sites": {},
    "jds": {},
    "appeals": {},
    "applications": {},
    "analyses": {},
    "comments": {},
    "plans": {},
    "banks": {},
    "credit_txns": {},
    "permits": {},
    "reports": {},
    "cases": {},
}

# ---------------------------------------------------------------------------
# Logical clock. Startup default is exactly 2026-09-01T00:00:00Z; it never
# falls back to wall-clock time (PRD §2.5).
# ---------------------------------------------------------------------------
_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Insertion sequence: stable tiebreaker for created_at-ascending list sorts,
# since many creates can share one logical-clock instant.
_SEQ = 0


def get_clock():
    return _CLOCK


def set_clock(dt):
    global _CLOCK
    _CLOCK = dt


def next_seq():
    global _SEQ
    _SEQ += 1
    return _SEQ


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Timestamp helpers. All entity timestamps are ISO 8601 UTC with three
# fractional digits, e.g. 2026-09-01T00:00:00.000Z (PRD §2.4).
# ---------------------------------------------------------------------------

def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant (accepts trailing Z or numeric offset).

    Naive values are interpreted as UTC. Raises ValueError on bad input.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def wall_now_iso():
    """Wall-clock UTC timestamp for the response meta block."""
    return iso(datetime.now(timezone.utc))


def sort_key(entity):
    """created_at ascending with insertion-order tiebreak."""
    return (entity["created_at"], entity["created_seq"])


def new_entity(fields):
    """Assemble a new entity dict with the four common fields (PRD §2.4).

    version starts at 1 and is incremented by exactly 1 on every mutation;
    created_at/updated_at are the current logical clock.
    """
    now = get_clock()
    entity = {"id": new_id(), "version": 1, "created_at": now, "updated_at": now,
              "created_seq": next_seq()}
    entity.update(fields)
    return entity


def bump(entity):
    """Mark a mutation: version += 1, updated_at := current logical clock."""
    entity["version"] += 1
    entity["updated_at"] = get_clock()
