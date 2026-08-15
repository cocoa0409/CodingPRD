"""In-memory store plus the server-held logical clock.

The store starts empty on every boot; the logical clock starts at exactly
2026-08-01T00:00:00Z (PRD section 2.4). All temporal reasoning uses this clock,
never the host wall clock.
"""

import uuid
from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clock = CLOCK_DEFAULT
        self.seq = 0
        self.patients = {}
        self.suppliers = {}
        self.supplier_orders = {}
        self.units = {}
        self.type_and_screens = {}
        self.orders = {}
        self.crossmatches = {}
        self.mtps = {}
        self.issues = {}
        self.reactions = {}
        self.recalls = {}
        self.wastage = {}
        self.policies = {}
        self.coolers = {}
        self.checkouts = {}


DB = Store()


def now():
    return DB.clock


def set_clock(value):
    DB.clock = value


def _next_seq():
    DB.seq += 1
    return DB.seq


def new_entity(fields):
    """Create a record carrying the standard system-managed fields (PRD 2.5)."""
    ts = now()
    entity = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": _next_seq(),
    }
    entity.update(fields)
    return entity


def new_event(fields):
    """Append-only record (WastageRecord): id + created_at only (PRD 2.5)."""
    entity = {
        "id": str(uuid.uuid4()),
        "created_at": now(),
        "_seq": _next_seq(),
    }
    entity.update(fields)
    return entity


def touch(entity):
    """Refresh updated_at and increment version on any mutation (PRD 2.5)."""
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 1) + 1
