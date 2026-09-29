"""In-memory store. Starts empty on every boot; nothing is ever seeded."""
import uuid

from flask import g

import clock

merchants = {}
agreements = {}
negotiation_rounds = {}
employers = {}
eligibility_files = {}
memberships = {}
offers = {}
placement_slots = {}
redemptions = {}
disputes = {}
statements = {}
ledger_entries = {}

_ALL = [
    merchants, agreements, negotiation_rounds, employers, eligibility_files,
    memberships, offers, placement_slots, redemptions, disputes, statements,
    ledger_entries,
]

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def _touched_set():
    try:
        bag = getattr(g, "_touched_rows", None)
        if bag is None:
            bag = set()
            g._touched_rows = bag
        return bag
    except RuntimeError:
        return set()


def insert(store, fields, versioned=True):
    """Create a row with the common system-managed properties (PRD 2.5)."""
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = clock.now()
    row["_seq"] = next_seq()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    store[row["id"]] = row
    # A freshly created row is already at its final version for this request.
    _touched_set().add(row["id"])
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1 (PRD 2.5 / 2.8).

    Section 2.8 states that each row the server touches has its version
    incremented by 1 for the request, so a row reached twice inside one
    cascade still only advances once.
    """
    if row is None:
        return row
    bag = _touched_set()
    if row["id"] in bag:
        return row
    bag.add(row["id"])
    row["updated_at"] = clock.now()
    row["version"] = int(row.get("version", 1)) + 1
    return row


def sorted_rows(rows):
    """Default list order: created_at ASC, insertion order as the tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def reset():
    for store in _ALL:
        store.clear()
    _seq["n"] = 0
    clock.reset()
