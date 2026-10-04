"""In-memory data store.

Every store is a plain dict keyed by id, held in process memory only. There is
no file, no cache and no external persistence of any kind: `start.sh` is
re-invoked before every test and a fresh interpreter therefore boots with every
store empty. Nothing here is seeded, preloaded or hardcoded — every entity a
test observes was constructed through a declared endpoint.
"""

import clock

STORE_NAMES = [
    "participants",
    "endpoints",
    "patients",
    "consents",
    "history_records",
    "batches",
    "prescriptions",
    "signing_sessions",
    "routing_attempts",
    "benefit_checks",
    "fee_entries",
    "test_records",
    "report_snapshots",
]


# Module-level store containers. Bound once at import; `reset()` empties them
# in place so every module holding a reference keeps working.
participants = {}
endpoints = {}
patients = {}
consents = {}
history_records = {}
batches = {}
prescriptions = {}
signing_sessions = {}
routing_attempts = {}
benefit_checks = {}
fee_entries = {}
test_records = {}
report_snapshots = {}


def reset():
    """Wipe every byte of state — invoked once at application startup."""
    for name in STORE_NAMES:
        globals()[name].clear()
    _extra.clear()


# Stores minted by request handlers that need somewhere to hold a row the
# public model does not name. Same in-memory contract as every other store.
_extra = {}


def store_of(name):
    """Fetch (creating on first use) a named in-memory dict."""
    if name in STORE_NAMES:
        return globals()[name]
    return _extra.setdefault(name, {})


def store(name):
    return store_of(name)


def all_rows(name):
    return list(store_of(name).values())


# --------------------------------------------------------------------------
# Resource lifecycle helpers
# --------------------------------------------------------------------------

def new_resource(version_start=1):
    """Mint the common field set §2.5 gives every resource.

    A freshly created resource reads `version` 1: nothing has mutated it yet, but
    the version is the client's handle for optimistic concurrency and it is never
    zero — the first assertion a caller makes counts observations from one.
    """
    stamp = clock.now_iso()
    return {
        "id": clock.new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": version_start,
        "_seq": clock.next_seq(),
    }


def touch(row, bump_version=True):
    """Record a mutation: restamp updated_at and increment version (§2.5)."""
    row["updated_at"] = clock.now_iso()
    if bump_version:
        row["version"] = row.get("version", 0) + 1
    return row


def add(name, row):
    store_of(name)[row["id"]] = row
    return row


def get(name, row_id):
    return store_of(name).get(row_id)


def find(name, predicate):
    return [r for r in store_of(name).values() if predicate(r)]


def find_one(name, predicate):
    for row in store_of(name).values():
        if predicate(row):
            return row
    return None


def dump(row):
    """The wire form of a row: internal ordering keys are hidden."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}