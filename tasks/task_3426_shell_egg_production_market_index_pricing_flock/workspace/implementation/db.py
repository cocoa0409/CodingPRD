"""In-memory store plus the logical clock.

The store starts completely empty on every boot (the test harness restarts the
server per test); nothing is seeded. Every entity any test needs is built via
the declared API surface.

Datetime bookkeeping convention: every datetime field F is stored twice —
  ent["F"]       -> string echoed back in responses (the raw input string for
                    input-supplied fields, the canonical server format for
                    system-stamped fields), or None
  ent["_dt_F"]   -> the parsed aware-UTC datetime used for all comparisons and
                    arithmetic, or None
Internal keys start with "_" and are never serialized.
"""

from datetime import datetime, timezone

from util import canonical_iso, new_id

INITIAL_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clock = INITIAL_CLOCK
        self.seq = 0
        self.complexes = {}
        self.houses = {}
        self.certifications = {}
        self.flocks = {}
        self.disease_events = {}
        self.depopulation_orders = {}
        self.quotations = {}
        self.customers = {}
        self.commitments = {}
        self.orders = {}
        self.settlements = {}
        self.feed_contracts = {}
        self.feed_batches = {}
        self.packing_runs = {}
        self.capital_projects = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


STORE = Store()


def stamp_new(ent, versioned=True):
    """Populate the common system fields at creation (PRD §2.5).

    MarketQuotation passes versioned=False: it carries only id + created_at.
    """
    ent["id"] = new_id()
    ent["_seq"] = STORE.next_seq()
    ent["created_at"] = canonical_iso(STORE.clock)
    if versioned:
        ent["updated_at"] = ent["created_at"]
        ent["version"] = 1


def touch(ent):
    """Refresh updated_at and bump version after any mutation (including
    cascade-delivered ones, PRD §2.8)."""
    ent["updated_at"] = canonical_iso(STORE.clock)
    ent["version"] = ent.get("version", 0) + 1


def set_dt(ent, field, dt):
    """System-stamped datetime: canonical string + parsed datetime."""
    ent[field] = canonical_iso(dt)
    ent["_dt_" + field] = dt


def set_dt_raw(ent, field, raw, dt):
    """Input-supplied datetime: echo the raw string, keep the parsed value."""
    ent[field] = raw
    ent["_dt_" + field] = dt


def clear_dt(ent, field):
    ent[field] = None
    ent["_dt_" + field] = None
