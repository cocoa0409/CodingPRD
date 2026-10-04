# In-memory data store. Blank on every boot — no seeding, no persistence.
import itertools
import uuid

import constants as C
from timeutil import parse_iso


class Store:
    def __init__(self):
        self.parts = {}
        self.customers = {}
        self.pricing_schedules = {}
        self.orders = {}
        self.order_lines = {}
        self.capacity_pools = {}
        self.allocation_runs = {}
        self.eol_notices = {}
        self.lifetime_buys = {}
        self.site_qualifications = {}
        self.reference_designs = {}
        self.design_wins = {}
        # Monotonic creation sequence — stable tie-break when created_at ties
        # (the logical clock is fixed unless advanced).
        self.seq = itertools.count(1)
        self.clock = parse_iso(C.DEFAULT_CLOCK_UTC)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self.seq)

    def now(self):
        return self.clock

    def stamp(self):
        """Fresh common-fields bundle for a new entity."""
        now = self.clock
        return {
            "id": self.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "seq": self.next_seq(),
        }

    def touch(self, entity):
        """Mark a stored-field mutation: refresh updated_at, bump version."""
        entity["updated_at"] = self.clock
        entity["version"] += 1


store = Store()
