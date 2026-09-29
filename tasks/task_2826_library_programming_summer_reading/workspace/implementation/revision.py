"""Version and updated_at bookkeeping.

PRD 2.4: any resource whose stored fields changed during a request has advanced
its `version` by exactly 1 by the time the response is written -- including
resources that only changed because a derived roll-up moved.  Two mechanisms
implement that: handlers explicitly `mark()` the resources they transition, and
a snapshot diff taken across the whole store catches every roll-up the request
moved indirectly.  A resource is never bumped more than once per request.
"""

import store
from core import clock
from derive import SERIALIZERS

# Tables whose entities carry version/updated_at (ReadingLogEntry does not).
VERSIONED_TABLES = [
    "branches",
    "rooms",
    "programs",
    "reservations",
    "presenters",
    "contracts",
    "challenges",
    "tiers",
    "participants",
    "lots",
    "awards",
]

_state = {"snapshot": None, "marked": set()}


def _fingerprint(table, entity):
    payload = SERIALIZERS[table](entity)
    payload.pop("updated_at", None)
    payload.pop("version", None)
    return repr(sorted(payload.items(), key=lambda kv: kv[0]))


def begin():
    snapshot = {}
    for table in VERSIONED_TABLES:
        for entity in store.DB[table].values():
            snapshot[(table, entity["id"])] = _fingerprint(table, entity)
    _state["snapshot"] = snapshot
    _state["marked"] = set()


def mark(entity):
    """Force a version bump for a resource this request transitioned."""
    if entity is not None and "version" in entity:
        _state["marked"].add(entity["id"])


def finish():
    snapshot = _state["snapshot"]
    if snapshot is None:
        return
    marked = _state["marked"]
    now = clock.now()
    for table in VERSIONED_TABLES:
        for entity in store.DB[table].values():
            key = (table, entity["id"])
            before = snapshot.get(key)
            if before is None:
                # Created during this request: it stays at version 1.
                continue
            if entity["id"] in marked or _fingerprint(table, entity) != before:
                entity["version"] += 1
                entity["updated_at"] = now
    _state["snapshot"] = None
    _state["marked"] = set()


def abort():
    _state["snapshot"] = None
    _state["marked"] = set()
