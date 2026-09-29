"""In-memory data store.

Every collection starts empty on every boot: nothing is ever seeded, preloaded
or hardcoded here. Tests build all state through the declared endpoints.
"""

import clock
import util

programs = {}
eligibility_rules = {}
stackability_constraints = {}
dealers = {}
objectives = {}
protests = {}
deliveries = {}
claims = {}
payment_batches = {}
chargebacks = {}
budget_accruals = {}
repricing_events = {}

_seq = 0


def next_seq():
    """Monotonic insertion counter used as the tie-break for created_at ASC."""
    global _seq
    _seq += 1
    return _seq


def insert(collection, kind, entity, versioned=True):
    entity["id"] = util.new_id()
    entity["_kind"] = kind
    entity["_seq"] = next_seq()
    entity["created_at"] = clock.now()
    if versioned:
        entity["updated_at"] = entity["created_at"]
        entity["version"] = 1
    collection[entity["id"]] = entity
    return entity


def ordered(values):
    """created_at ASC, insertion order breaking ties on identical instants."""
    return sorted(values, key=lambda e: (e["created_at"], e["_seq"]))
