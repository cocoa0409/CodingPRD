"""In-memory data store.

Everything lives in plain dicts keyed by id.  There is no persistence of any
kind: re-invoking start.sh starts a brand-new process with a brand-new empty
store, and nothing is ever seeded at boot.
"""

import uuid

import clock

# Collections, keyed by resource id.
developers = {}
investors = {}
funds = {}
subscriptions = {}
projects = {}
allocations = {}
calls = {}
guarantees = {}
reviews = {}
exits = {}

# Monotonic insertion counter, used as the tie-break for "ascending order of
# creation timestamp" (PRD 2.3) when the logical clock has not moved.
_seq = 0


def reset():
    """Wipe every collection and restart the sequence counter."""
    global _seq
    for coll in (developers, investors, funds, subscriptions, projects,
                 allocations, calls, guarantees, reviews, exits):
        coll.clear()
    _seq = 0
    clock.reset()


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def create(collection, fields):
    """Insert a new row, stamping the four system-managed common fields."""
    rid = fields.get("id") or new_id()
    row = dict(fields)
    row["id"] = rid
    row["created_at"] = clock.now_str()
    row["updated_at"] = row["created_at"]
    row["version"] = 1
    row["_seq"] = next_seq()
    collection[rid] = row
    return row


def touch(row):
    """A modification: refresh updated_at and bump version by one (PRD 2.6)."""
    row["updated_at"] = clock.now_str()
    row["version"] = int(row.get("version", 0)) + 1
    return row


def ordered(rows):
    """Ascending creation order, with insertion sequence as the tie-break."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def listing(collection, filters=None):
    """Filter a collection and return it in default creation order."""
    rows = list(collection.values())
    if filters:
        for key, value in filters.items():
            if value is None:
                continue
            rows = [r for r in rows if r.get(key) == value]
    return ordered(rows)


def public(row):
    """Strip internal bookkeeping keys before the row goes over the wire."""
    return {k: v for k, v in row.items() if not k.startswith("_")}
