"""In-memory data store.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or hardcoded:
every row any caller needs is built through the declared endpoints.
"""

import uuid

collectives = {}
membership_tiers = {}
donor_members = {}
commitments = {}
contributions = {}
athletes = {}
deal_contracts = {}
deliverables = {}
payment_releases = {}
communication_logs = {}

# Monotonic per-entity-type insertion counters (PRD 2.4). Each starts at 1 and is
# never reused. The collective itself carries no sequence_no, but still needs a
# deterministic insertion order for its list endpoint.
_counters = {
    "collective_order": 0,
    "membership_tier": 0,
    "donor_member": 0,
    "commitment": 0,
    "contribution": 0,
    "athlete": 0,
    "deal_contract": 0,
    "deliverable": 0,
    "payment_release": 0,
    "communication_log": 0,
}


def next_seq(kind):
    _counters[kind] += 1
    return _counters[kind]


def new_id():
    return str(uuid.uuid4())


def ordered(rows):
    """Ascending sequence_no — the sort order for every list and every cascade."""
    return sorted(rows, key=lambda r: r["sequence_no"])


def ordered_collectives(rows):
    return sorted(rows, key=lambda r: r["_order"])


def reset_all():
    for table in (collectives, membership_tiers, donor_members, commitments,
                  contributions, athletes, deal_contracts, deliverables,
                  payment_releases, communication_logs):
        table.clear()
    for key in _counters:
        _counters[key] = 0
