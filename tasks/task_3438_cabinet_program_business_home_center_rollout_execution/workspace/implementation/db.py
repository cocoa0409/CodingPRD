"""In-memory store. Fresh per process; never seeded with entity data."""
from datetime import datetime, timezone

from util import iso3, new_id


class Store:
    def __init__(self):
        self.accounts = {}
        self.programs = {}
        self.lines = {}
        self.batches = {}
        self.design_jobs = {}
        self.orders = {}
        self.slots = {}
        self.shipments = {}
        self.claims = {}
        self.replacements = {}
        self.resets = {}
        # Logical clock (PRD 2.4): default reading 2026-09-01T00:00:00Z.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Internal bookkeeping (never serialized):
        self.order_priced_line = {}   # order_id -> ProgramLine id the order priced against
        self.order_slot_picks = {}    # order_id -> [(slot_id, family_code, units)]
        self.repl_slot_picks = {}     # replacement_id -> (slot_id, units)


store = Store()


def new_entity():
    """Common fields per PRD 2.5: id, created_at, updated_at, version.

    PRD 1/2.4: the system reads a single logical clock, never wall-clock
    time — timestamps are stamped from that clock.
    """
    ts = iso3(store.clock)
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def bump(entity):
    """PRD 2.5: every mutation refreshes updated_at and increments version."""
    entity["version"] += 1
    entity["updated_at"] = iso3(store.clock)
