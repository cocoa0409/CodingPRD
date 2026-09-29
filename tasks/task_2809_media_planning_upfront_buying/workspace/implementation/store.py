"""In-memory state (PRD 2.1).

Plain dicts keyed by id.  Nothing is persisted and nothing is seeded: the
process starts completely empty on every boot, which is what makes
per-test-server isolation a real wipe.
"""

import uuid

from flask import g

from constants import CLOCK_EPOCH
from timeutil import parse_ts

COLLECTIONS = (
    "advertisers",
    "campaigns",
    "allocations",
    "sellers",
    "forecasts",
    "negotiations",
    "buys",
    "units",
    "reports",
    "make_goods",
    "rights",
    "runs",
    "invoices",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_ts(CLOCK_EPOCH)
        self._seq = 0

    # --- logical clock ------------------------------------------------------
    def now(self):
        """The logical clock.  Never the wall clock (PRD 2.3)."""
        return self.clock

    def set_clock(self, dt):
        self.clock = dt

    # --- identity ----------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def new(self, collection, fields, versioned=True):
        """Insert a record, stamping id / created_at / updated_at / version."""
        rec = dict(fields)
        rec["id"] = str(uuid.uuid4())
        rec["created_at"] = self.now()
        rec["_seq"] = self.next_seq()
        if versioned:
            rec.setdefault("updated_at", self.now())
            rec["updated_at"] = self.now()
            rec["version"] = 1
        getattr(self, collection)[rec["id"]] = rec
        return rec

    # --- mutation bookkeeping ---------------------------------------------
    def touch(self, rec):
        """Advance updated_at and bump version once per record per request.

        A single request may both recompute a derived aggregate and advance a
        state machine; PRD 2.3 counts that as one mutation of the resource, so
        the version increments at most once no matter how many code paths
        touch the record.
        """
        if rec is None or "version" not in rec:
            return rec
        try:
            seen = g._touched
        except (AttributeError, RuntimeError):
            seen = None
        key = rec.get("id")
        if seen is not None:
            if key in seen:
                rec["updated_at"] = self.now()
                return rec
            seen.add(key)
        rec["version"] += 1
        rec["updated_at"] = self.now()
        return rec


store = Store()


def sorted_records(values):
    """Default ordering: created_at ascending, insertion order breaking ties."""
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))
