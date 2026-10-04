"""In-memory object store.

Nothing is persisted and nothing is seeded: the store starts empty on every
boot and every row is created through a declared endpoint (PRD 2.5, 3.1).
"""

import uuid

import clock

KINDS = (
    "organizations",
    "programs",
    "filings",
    "extracted_fields",
    "leadership_members",
    "demographic_records",
    "seals",
    "grants",
    "licenses",
    "usage_events",
    "correction_requests",
    "identity_cases",
)

DB = {kind: {} for kind in KINDS}
ORDER = {kind: [] for kind in KINDS}


def reset():
    """Wipe every byte of state — used when the process starts."""
    for kind in KINDS:
        DB[kind].clear()
        ORDER[kind] = []


def new_id():
    """Server-minted UUID string with no type prefix (PRD 2.5)."""
    return str(uuid.uuid4())


def new_row(**fields):
    """Create a row carrying the four system-managed common properties."""
    stamp = clock.fmt_dt(clock.now())
    row = {"id": new_id(), "created_at": stamp, "updated_at": stamp, "version": 1}
    row.update(fields)
    return row


def insert(kind, row):
    DB[kind][row["id"]] = row
    ORDER[kind].append(row["id"])
    return row


def touch(row):
    """A mutation: bump version by 1 and refresh updated_at (PRD 2.5)."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = clock.fmt_dt(clock.now())
    return row


def rows(kind):
    """All rows of a kind, in creation order (ties broken deterministically)."""
    return [DB[kind][rid] for rid in ORDER[kind]]


def find(kind, row_id):
    return DB[kind].get(row_id)


def where(kind, **criteria):
    out = []
    for row in rows(kind):
        if all(row.get(key) == value for key, value in criteria.items()):
            out.append(row)
    return out


def children(kind, **criteria):
    return where(kind, **criteria)


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more
