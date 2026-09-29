"""The in-memory store and the logical clock.

Everything lives in plain Python dicts held by a single module-level Store
instance.  There is no persistence of any kind: a fresh process starts with an
empty programme, and every entity a caller needs must be created through the
declared endpoints.
"""

import itertools
import uuid

import config
import timeutil


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        # One dict per collection, keyed by the server-minted UUID.
        self.partners = {}
        self.products = {}
        self.premises = {}
        self.campaigns = {}
        self.enrollments = {}
        self.claims = {}
        self.contractors = {}
        self.dispatches = {}
        self.ledger_entries = {}
        self.complaints = {}
        # The logical clock. Only POST /_clock/set_current_utc moves it.
        self.clock = timeutil.parse_instant(config.CLOCK_START)
        self._counter = itertools.count(1)

    # --------------------------------------------------------------- the clock
    def now(self):
        return self.clock

    def now_iso(self):
        return timeutil.render_instant(self.clock)

    def today(self):
        return timeutil.instant_to_date(self.clock)

    def set_clock(self, dt):
        self.clock = dt

    def next_seq(self):
        return next(self._counter)


store = Store()


def new_id():
    return str(uuid.uuid4())


def create_record(collection, body, versioned=True):
    """Insert a new record, stamping the read-only system fields."""
    rec = {"id": new_id()}
    rec.update(body)
    rec["created_at"] = store.now_iso()
    if versioned:
        rec["updated_at"] = store.now_iso()
        rec["version"] = 1
    rec["_seq"] = store.next_seq()
    collection[rec["id"]] = rec
    return rec


def _touched_this_request():
    """The set of record ids already versioned inside the current request."""
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return None
        if not hasattr(g, "_touched_ids"):
            g._touched_ids = set()
        return g._touched_ids
    except Exception:  # pragma: no cover - outside any Flask context
        return None


def touch(rec):
    """Register one accepted mutation on a record: bump version and updated_at.

    A record that several hops of the same cascade reach is versioned exactly
    once for the whole request, which is what PRD 2.4 means by "every record
    actually touched has its own version incremented by 1".
    """
    rec["updated_at"] = store.now_iso()
    seen = _touched_this_request()
    if seen is not None:
        if rec["id"] in seen:
            return rec
        seen.add(rec["id"])
    rec["version"] = rec.get("version", 0) + 1
    return rec


def sort_key(rec):
    """Canonical ordering: created_at ascending, insertion order as tie-break."""
    return (rec["created_at"], rec["_seq"])


def ordered(collection, predicate=None):
    """Every record of a collection in created_at ascending order."""
    values = collection.values()
    if predicate is not None:
        values = [r for r in values if predicate(r)]
    return sorted(values, key=sort_key)


def get(collection, record_id):
    if not isinstance(record_id, str):
        return None
    return collection.get(record_id)
