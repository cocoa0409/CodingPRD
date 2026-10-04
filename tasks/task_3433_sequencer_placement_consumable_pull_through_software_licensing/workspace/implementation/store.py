"""In-memory data store and the logical clock.

The store starts empty on every boot — no seeding. The logical clock defaults
to exactly 2026-09-01T00:00:00Z and only advances via POST /genomics/_clock/set_current_utc.
"""

import uuid
from datetime import datetime, timezone

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

DB = {
    "accounts": {},
    "models": {},
    "kits": {},
    "updates": {},
    "instruments": {},
    "programs": {},
    "lots": {},
    "orders": {},
    "contracts": {},
    "licenses": {},
    "runs": {},
    "transitions": {},
    "forecasts": {},
}

CLOCK = {"now": CLOCK_START}
SEQ = {"n": 0}


def now():
    return CLOCK["now"]


def set_clock(value):
    CLOCK["now"] = value


def new_id():
    return str(uuid.uuid4())


def next_seq():
    SEQ["n"] += 1
    return SEQ["n"]


def stamp_new(entity):
    """Initialize common system fields at creation (logical clock)."""
    entity["created_at"] = CLOCK["now"]
    entity["updated_at"] = CLOCK["now"]
    entity["version"] = 1
    entity["_seq"] = next_seq()


def stamp_new_run(entity):
    """Run records carry only id + created_at (no updated_at / version)."""
    entity["created_at"] = CLOCK["now"]
    entity["_seq"] = next_seq()


def touch(entity):
    """Every mutation bumps version by one and refreshes updated_at (PRD 2.5)."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = CLOCK["now"]
