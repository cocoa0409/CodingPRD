"""In-memory object store, logical clock and identifier/timestamp helpers.

Storage is process-local and starts empty on every boot.  Nothing is ever
seeded, preloaded or written to disk: every entity a caller reads was created
through a declared endpoint in the same process lifetime.
"""

import random
import string
import threading
import uuid
from datetime import datetime, timezone



class Clock:
    """Logical clock.  Starts at exactly 2026-09-01T00:00:00Z and only ever
    moves when an operator calls POST /_clock/set_current_utc."""

    DEFAULT = "2026-09-01T00:00:00Z"

    def __init__(self):
        self._now = fmt(datetime(2026, 9, 1, tzinfo=timezone.utc))

    def now(self):
        return self._now

    def now_dt(self):
        return parse_dt(self._now)

    def set(self, value):
        self._now = fmt(parse_dt(value))


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def new_id():
    """Opaque UUID identifier; no type prefix, no entity-name segment."""
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(18))


def new_token(prefix=""):
    return prefix + uuid.uuid4().hex


def days_between(later, earlier):
    """Whole days between two instants (later - earlier)."""
    return (later.date() - earlier.date()).days


def dt_equal_day(a, b):
    return a.date() == b.date()


class Store:
    """Thread-safe collection bag keyed by entity name, then by id."""

    def __init__(self):
        self._lock = threading.RLock()
        self._collections = {}
        self.clock = Clock()
        self._seq = {}

    def coll(self, name):
        with self._lock:
            if name not in self._collections:
                self._collections[name] = dict()
            return self._collections[name]

    def all(self, name):
        with self._lock:
            return list(self.coll(name).values())

    def get(self, name, row_id):
        with self._lock:
            return self.coll(name).get(row_id)

    def put(self, name, row):
        with self._lock:
            self.coll(name)[row["id"]] = row
        return row

    def remove(self, name, row_id):
        with self._lock:
            self.coll(name).pop(row_id, None)

    def find(self, name, **criteria):
        out = []
        for row in self.all(name):
            if all(row.get(k) == v for k, v in criteria.items()):
                out.append(row)
        return out

    def find_one(self, name, **criteria):
        rows = self.find(name, **criteria)
        return rows[0] if rows else None

    def next_seq(self, name):
        with self._lock:
            self._seq[name] = self._seq.get(name, 0) + 1
            return self._seq[name]

    def wipe(self):
        with self._lock:
            self._collections = {}
            self._seq = {}


STORE = Store()