"""In-memory data store and the logical clock.

Everything here lives only in process memory: a fresh `start.sh` boot yields a
store with zero entities.  Nothing is seeded, preloaded or read back from disk.
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

ZERO = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    """ISO 8601 UTC instant.

    The fractional part is emitted only when the instant actually carries
    sub-second precision, so an instant landing on a whole second reads
    `2026-09-01T07:20:00Z` rather than `2026-09-01T07:20:00.000Z`.  The logical
    clock is whole-second granular, so every business instant is written the
    short way; the audit pair (`created_at`/`updated_at`) is normalized to the
    three-digit form on the way out (see serializers).
    """
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = parse_iso(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def trunc_minutes(delta):
    """Whole minutes, truncated toward zero."""
    return int(delta.total_seconds() // 60)


class Store(object):
    def __init__(self):
        self.stations = {}
        self.airlines = {}
        self.flights = {}
        self.makeup_areas = {}
        self.lanes = {}
        self.bags = {}
        self.scans = {}
        self.screenings = {}
        self.inspections = {}
        self.connections = {}
        self.special_items = {}
        self.reports = {}
        self.claims = {}
        self.deliveries = {}
        self.clock = ZERO
        self._seq = 0

    # -- creation sequence ---------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- clock ---------------------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt

    # -- ids -----------------------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def new_tag_number(self):
        while True:
            tag = "".join(random.choice("0123456789") for _ in range(10))
            if not any(b["tag_number"] == tag for b in self.bags.values()):
                return tag

    # -- generic collection helpers -----------------------------------------
    def collection(self, name):
        return getattr(self, name)

    def by_id(self, name, ident):
        return self.collection(name).get(ident)

    def find(self, name, **criteria):
        out = []
        for row in self.collection(name).values():
            if all(row.get(k) == v for k, v in criteria.items()):
                out.append(row)
        return out

    def add(self, name, row):
        self.collection(name)[row["id"]] = row
        return row

    def remove(self, name, ident):
        self.collection(name).pop(ident, None)

    def all_of(self, name):
        return list(self.collection(name).values())


DB = Store()


def new_row(store, fields):
    """A new principal resource row carrying the four common attributes."""
    stamp = iso(store.now())
    row = {
        "id": store.new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": store.next_seq(),
    }
    row.update(fields)
    return row


def touch(store, row):
    row["updated_at"] = iso(store.now())
    row["version"] = row.get("version", 0) + 1


def minutes_before(dt, minutes):
    return dt - timedelta(minutes=minutes)


def minutes_after(dt, minutes):
    return dt + timedelta(minutes=minutes)