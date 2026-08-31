"""In-memory data store. Starts completely empty on every boot: no seeding."""

import datetime
import itertools
import threading
import uuid

from errors import ApiError

LOCK = threading.RLock()

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Collection name -> {id: row}
COLLECTIONS = (
    "facilities",
    "concessionaires",
    "agreements",
    "counter_spaces",
    "counter_assignments",
    "zones",
    "fleet_allocations",
    "reports",
    "remittances",
    "obligations",
    "shuttle_periods",
    "shuttle_allocations",
    "projects",
    "disbursements",
    "settlements",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self.clock = DEFAULT_CLOCK

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (datetime.datetime.now(datetime.timezone.utc).microsecond // 1000)


def _stamp():
    dt = datetime.datetime.now(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def new_row(collection, data, versioned=True):
    """Insert a new row. `created_at`/`updated_at`/`version` per PRD 2.4."""
    row = dict(data)
    row["id"] = new_id()
    ts = _stamp()
    row["created_at"] = ts
    if versioned:
        row["updated_at"] = ts
        row["version"] = 1
    row["_seq"] = db.next_seq()
    getattr(db, collection)[row["id"]] = row
    return row


def touch(row, touched):
    """Bump updated_at/version at most once per request (PRD 2.4)."""
    if row is None:
        return
    key = id(row)
    if key in touched:
        return
    touched.add(key)
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = _stamp()


def all_rows(collection):
    rows = list(getattr(db, collection).values())
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def get(collection, row_id, err_key):
    if not isinstance(row_id, str):
        raise ApiError(err_key)
    row = getattr(db, collection).get(row_id)
    if row is None:
        raise ApiError(err_key)
    return row


def clock_date():
    """Calendar date (YYYY-MM-DD) of the logical clock."""
    return db.clock[:10]
