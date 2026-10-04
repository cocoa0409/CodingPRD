"""In-memory data store.

Every table is a plain dict keyed by id and starts empty on every boot: the
implementation encodes the system, never the data.  Each row also carries a
private `_seq` (append sequence) so that orderings which tie on the logical
clock's `created_at` remain deterministic.
"""

import uuid

import clock

members = {}
agreements = {}
loads = {}
bids = {}
ledger = {}
recalls = {}
holds = {}
audits = {}
programs = {}
pickups = {}

TABLES = {
    "members": members,
    "agreements": agreements,
    "loads": loads,
    "bids": bids,
    "ledger": ledger,
    "recalls": recalls,
    "holds": holds,
    "audits": audits,
    "programs": programs,
    "pickups": pickups,
}

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def insert(table, row):
    TABLES[table][row["id"]] = row
    return row


def new_record(**fields):
    """A first-class resource: id + created_at/updated_at/version."""
    stamp = clock.now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    row.update(fields)
    return row


def new_append_only(**fields):
    """ShareLedgerEntry / RecallHold: id + created_at only, never mutated."""
    row = {
        "id": new_id(),
        "created_at": clock.now(),
        "_seq": next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    """Record a mutation: refresh updated_at and bump version by one."""
    row["updated_at"] = clock.now()
    row["version"] = row.get("version", 1) + 1
    return row


def ordered(rows):
    """Creation-timestamp ascending, append sequence breaking ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def find(table, row_id):
    return TABLES[table].get(row_id)
