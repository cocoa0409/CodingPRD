"""In-memory data store.  Starts empty on every boot; nothing is ever seeded."""
import itertools
import uuid

import clock

customers = {}
device_models = {}
carrier_accounts = {}
credit_applications = {}
loans = {}
installments = {}
payment_postings = {}
device_units = {}
upgrade_requests = {}
trade_ins = {}
diagnostic_reports = {}
payoff_quotes = {}
delinquency_events = {}

_seq = itertools.count(1)

# Entity ids already version-bumped during the current request.  A single
# operation advances any entity's version by exactly one, no matter how many
# times the operation writes it (PRD 2.6, 2.8).
_touched = set()


def begin_request():
    _touched.clear()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def insert(store, record, append_only=False):
    """Mint id / created_at (and updated_at + version unless append-only)."""
    record["id"] = new_id()
    record["created_at"] = clock.now_iso()
    if not append_only:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    record["_seq"] = next_seq()
    store[record["id"]] = record
    _touched.add(record["id"])
    return record


def touch(record, bump_version=True):
    """Refresh updated_at and advance version by one (once per request)."""
    if record is None:
        return record
    record["updated_at"] = clock.now_iso()
    if bump_version and "version" in record:
        if record["id"] not in _touched:
            record["version"] = record["version"] + 1
            _touched.add(record["id"])
    return record


def ordered(records):
    """Default ordering: created_at ascending, insertion order as tie-break."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def values(store):
    return ordered(list(store.values()))


def find_one(store, **predicate):
    for record in values(store):
        if all(record.get(key) == value for key, value in predicate.items()):
            return record
    return None


def find_all(store, **predicate):
    return [r for r in values(store)
            if all(r.get(key) == value for key, value in predicate.items())]
