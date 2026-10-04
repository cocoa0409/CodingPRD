"""In-memory data store.

Everything lives in plain dicts keyed by id.  Nothing is persisted, nothing is
seeded: the store starts empty on every boot and every entity is built through
the declared API surface.  `_seq` gives a stable insertion order so list
endpoints can tie-break rows that share the same logical-clock `created_at`.
"""

import itertools
import uuid

import timeutil

TABLES = (
    "partners",
    "students",
    "cohorts",
    "agreements",
    "placements",
    "interview_rounds",
    "stipend_statements",
    "satisfaction_records",
    "outcome_checkpoints",
    "invoices",
    "credit_grants",
)

store = {name: {} for name in TABLES}

_seq = itertools.count(1)


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def make_row(**fields):
    """Create a row carrying the four system-managed common properties."""
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = timeutil.now()
    row["updated_at"] = row["created_at"]
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def insert(table, row):
    store[table][row["id"]] = row
    return row


def get(table, row_id):
    if row_id is None:
        return None
    return store[table].get(row_id)


def all_rows(table):
    return list(store[table].values())


def touch(row):
    """Record a mutation: refresh updated_at and bump version."""
    row["updated_at"] = timeutil.now()
    row["version"] = int(row.get("version", 1)) + 1
    return row


def reset():
    for name in TABLES:
        store[name] = {}
