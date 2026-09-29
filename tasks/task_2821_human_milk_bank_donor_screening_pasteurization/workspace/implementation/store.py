"""In-memory data store, logical clock and per-request mutation tracking.

Everything lives in plain dicts keyed by id; nothing is persisted and nothing is
seeded — every row in the bank is created by a declared endpoint.

Version discipline (PRD 2.4 / 2.8): a row that a request mutates gets exactly
one `version` increment and one refreshed `updated_at`, no matter how many of
its fields (or how many cascade hops) touched it.  Rows created by the request
are born at version 1 and are excluded.  `touch()` is therefore called on every
real field change and the increment happens once, at request end.
"""

from datetime import datetime

from util import UTC, fmt_instant, new_id

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

# Entities carrying the full audit set (id, created_at, updated_at, version).
VERSIONED = {
    "donors", "shipments", "donations", "pools", "runs", "lots",
    "programs", "prescriptions", "dispenses",
}


class DB(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.donors = {}
        self.questionnaires = {}
        self.serology = {}
        self.approvals = {}
        self.shipments = {}
        self.donations = {}
        self.pools = {}
        self.components = {}
        self.runs = {}
        self.readings = {}
        self.lots = {}
        self.programs = {}
        self.prescriptions = {}
        self.dispenses = {}
        self.deferrals = {}

        self.clock = CLOCK_START
        self.pool_sequence_counter = 0
        self.cycle_counter = 0
        self.row_counter = 0

        self._dirty = {}
        self._fresh = set()

    # -- clock ------------------------------------------------------------
    def clock_instant(self):
        return fmt_instant(self.clock)

    def clock_date(self):
        return self.clock.date()

    # -- collections ------------------------------------------------------
    def collection(self, name):
        return getattr(self, name)

    def rows(self, name):
        """Rows of a collection in insertion order."""
        return sorted(getattr(self, name).values(), key=lambda r: r["_seq"])

    def insert(self, name, row):
        self.row_counter += 1
        row["id"] = row.get("id") or new_id()
        row["_seq"] = self.row_counter
        row["created_at"] = self.clock_instant()
        if name in VERSIONED:
            row["updated_at"] = row["created_at"]
            row["version"] = 1
        getattr(self, name)[row["id"]] = row
        self._fresh.add(id(row))
        return row

    # -- mutation tracking ------------------------------------------------
    def touch(self, row):
        """Mark a row mutated; the first touch of a request carries the audit.

        The increment happens on the first touch rather than at request end so
        that a response body serialized by the view already shows the new
        `version` and `updated_at`.  Later touches of the same row inside the
        same request are absorbed, which is what gives a multi-hop cascade
        exactly one increment per row (PRD 2.4 / 2.8).
        """
        if row is None:
            return
        key = id(row)
        if key in self._fresh or key in self._dirty:
            return
        self._dirty[key] = row
        if "version" in row:
            row["version"] = int(row["version"]) + 1
            row["updated_at"] = self.clock_instant()

    def set_field(self, row, key, value):
        """Assign and mark the row mutated only when the value really changes."""
        if row.get(key) != value:
            row[key] = value
            self.touch(row)
            return True
        return False

    def rearm(self, *rows):
        """Re-open the audit window for specific rows.

        A row already mutated earlier in this request takes a further `version`
        increment on its next real field change.  The allocation cycle needs
        this because every draw it makes "creates a fill exactly as a manual
        fill would ... applying the same ledger consequences to the lot, the
        subsidy program and the prescription" (PRD 3.10), and each of those
        ledger applications carries its own `version` increment (PRD 3.9).  A
        cycle is a sequence of independent fills, not one cascade, so the
        absorb rule of `touch()` must not swallow the second fill.  Rows
        created by this request stay excluded: they are born at version 1.
        """
        for row in rows:
            if row is not None:
                self._dirty.pop(id(row), None)

    def begin(self):
        self._dirty = {}
        self._fresh = set()

    def commit(self):
        """Close the request's mutation window (the audit is already applied)."""
        self._dirty = {}
        self._fresh = set()


db = DB()


def clock_instant():
    return db.clock_instant()


def clock_date():
    return db.clock_date()


def touch(row):
    db.touch(row)


def set_field(row, key, value):
    return db.set_field(row, key, value)


def insert(name, row):
    return db.insert(name, row)


def find(name, row_id):
    if not isinstance(row_id, str):
        return None
    return getattr(db, name).get(row_id)
