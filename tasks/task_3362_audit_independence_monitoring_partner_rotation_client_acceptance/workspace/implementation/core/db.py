"""In-memory data store.

The store is process-local and starts empty on every boot. Nothing is seeded,
preloaded or persisted: every row is created through a declared endpoint.
"""

from .utils import format_timestamp, new_id, utcnow

COLLECTIONS = (
    "clients",
    "engagements",
    "acceptances",
    "assessments",
    "professionals",
    "assignments",
    "findings",
    "threats",
    "services",
    "affiliates",
    "attestations",
    "reviews",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def mint_id():
    return new_id()


def new_row(collection, values):
    """Create a row: system-managed common fields plus a stable insertion seq."""
    now = utcnow()
    row = {
        "id": mint_id(),
        "created_at": format_timestamp(now),
        "updated_at": format_timestamp(now),
        "version": 1,
        "_seq": store.next_seq(),
        "_created_dt": now,
    }
    row.update(values)
    getattr(store, collection)[row["id"]] = row
    return row


def touch(row, now=None):
    """Refresh updated_at and bump version by one."""
    row["updated_at"] = format_timestamp(now or utcnow())
    row["version"] = int(row.get("version", 1)) + 1


def set_fields(row, **changes):
    """Apply changes, touching the row only when a value actually moved."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def all_rows(collection):
    return list(getattr(store, collection).values())


def find(collection, row_id):
    if not row_id:
        return None
    return getattr(store, collection).get(row_id)


def rows_where(collection, predicate):
    return [row for row in all_rows(collection) if predicate(row)]


def ordered(rows):
    return sorted(rows, key=lambda row: (row.get("_seq", 0)))


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total
