"""Purely in-memory data store. Empty on every boot; nothing is ever seeded."""

import uuid

from clock import clock


class Store:
    def __init__(self):
        self.members = {}
        self.leagues = {}
        self.teams = {}
        self.memberships = {}
        self.fee_remittances = {}
        self.lane_pairs = {}
        self.matches = {}
        self.series_entries = {}
        self.dues_payments = {}
        self.prize_funds = {}
        self.prize_awards = {}
        self.award_applications = {}
        self.protests = {}
        self._seq = 0
        self._national_seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_national_number(self):
        self._national_seq += 1
        return "NM-%06d" % self._national_seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def insert(table, row, versioned=True):
    """Insert a fresh row, stamping identity and system fields."""
    row["id"] = new_id()
    row["created_at"] = clock.now()
    if versioned:
        row["updated_at"] = clock.now()
        row["version"] = 1
    row["_seq"] = store.next_seq()
    table[row["id"]] = row
    return row


def touch(row):
    """Record a mutation of a row: refresh updated_at and bump version by 1."""
    if "version" in row:
        row["updated_at"] = clock.now()
        row["version"] = row["version"] + 1
    return row


def apply_changes(row, changes):
    """Write the changed fields only; bump version once when anything changed."""
    dirty = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            dirty = True
    if dirty:
        touch(row)
    return dirty


def ordered(rows):
    """Default ordering: created_at ascending, insertion order as tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
