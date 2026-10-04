"""In-memory data store (PRD §2.5 common fields; no persistence, no seeding).

The store starts empty on every boot. Entities are plain dicts; datetimes are
stored as aware datetime objects and serialized by serialize.py.
"""

import uuid

import clock

# One dict per top-level collection (flat topology, PRD §2.11).
CASES = {}
ASSETS = {}
TRANSFERS = {}
VALUATIONS = {}
EXPENSES = {}
ISRS = {}
INTERESTS = {}
SALES = {}
DISTRIBUTIONS = {}

# Monotonic insertion sequence — deterministic tiebreak under created_at.
_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def new_entity(fields):
    """Stamp the common system fields (id/created_at/updated_at/version).

    created_at/updated_at read the server-side logical clock — PRD §2.4:
    "Time inside this API is defined by a server-side logical clock, never
    by wall-clock time."  Ordering ties under an unmoved clock break on the
    monotonic insertion sequence.
    """
    now = clock.now()
    entity = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    entity.update(fields)
    return entity


def touch(entity):
    """Record a mutation: version += 1 and updated_at refreshed (PRD §2.5)."""
    entity["version"] += 1
    entity["updated_at"] = clock.now()


def rederive_available(case):
    """available_proceeds_cents = net basis - equitable shares paid (§1.1)."""
    case["available_proceeds_cents"] = (
        case["sharing_pool_net_basis_cents"] - case["equitable_shares_paid_cents"]
    )


def assets_of_case(case_id):
    return [a for a in ASSETS.values() if a["seizure_case_id"] == case_id]


def valuations_of_asset(asset_id):
    return [v for v in VALUATIONS.values() if v["asset_id"] == asset_id]


def transfers_of_asset(asset_id):
    return [t for t in TRANSFERS.values() if t["asset_id"] == asset_id]


def expenses_of_asset(asset_id):
    return [e for e in EXPENSES.values() if e["asset_id"] == asset_id]


def isrs_of_asset(asset_id):
    return [i for i in ISRS.values() if i["asset_id"] == asset_id]


def interests_of_asset(asset_id):
    return [t for t in INTERESTS.values() if t["asset_id"] == asset_id]


def sales_of_asset(asset_id):
    return [s for s in SALES.values() if s["asset_id"] == asset_id]


def distributions_of_case(case_id):
    return [d for d in DISTRIBUTIONS.values() if d["seizure_case_id"] == case_id]
