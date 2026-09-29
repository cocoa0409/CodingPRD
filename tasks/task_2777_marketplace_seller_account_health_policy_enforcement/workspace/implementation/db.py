"""In-memory store. Starts empty on every boot; nothing is ever seeded."""

import uuid

from flask import g

import clock

SELLERS = {}
METRIC_SNAPSHOTS = {}
HEALTH_EVALUATIONS = {}
POLICY_RULES = {}
LISTINGS = {}
VIOLATIONS = {}
ENFORCEMENT_ACTIONS = {}
PLANS_OF_ACTION = {}
APPEALS = {}
DISBURSEMENT_HOLDS = {}
NOTIFICATIONS = {}
RELATED_ACCOUNT_LINKS = {}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def _dirty_map():
    d = getattr(g, "_dirty_rows", None)
    if d is None:
        d = {}
        g._dirty_rows = d
    return d


def _created_set():
    s = getattr(g, "_created_rows", None)
    if s is None:
        s = set()
        g._created_rows = s
    return s


def mark_dirty(row):
    if row is None:
        return
    _dirty_map()[id(row)] = row


def set_field(row, key, value):
    """Assign and mark the row dirty only when the stored value actually moves."""
    if row.get(key) != value:
        row[key] = value
        mark_dirty(row)


def new_row(kind, versioned=True, **fields):
    ts = clock.now()
    row = {"id": new_id(), "created_at": ts, "_kind": kind, "_seq": next_seq()}
    if versioned:
        row["updated_at"] = ts
        row["version"] = 1
    row.update(fields)
    _created_set().add(id(row))
    return row


def commit():
    """Bump version/updated_at once per mutated row, at the end of the request."""
    created = _created_set()
    ts = clock.now()
    for rid, row in list(_dirty_map().items()):
        if rid in created:
            continue
        if "version" not in row:
            continue
        row["version"] = row["version"] + 1
        row["updated_at"] = ts
    _dirty_map().clear()


def sorted_rows(table, key=None):
    rows = list(table.values())
    if key is None:
        rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    else:
        rows.sort(key=key)
    return rows


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# --- convenience accessors --------------------------------------------------

def listings_of(seller_id):
    return by_created([r for r in LISTINGS.values() if r["seller_id"] == seller_id])


def violations_of(seller_id):
    return by_created([r for r in VIOLATIONS.values() if r["seller_id"] == seller_id])


def actions_of(seller_id):
    return by_created(
        [r for r in ENFORCEMENT_ACTIONS.values() if r["seller_id"] == seller_id]
    )


def holds_of(seller_id):
    return by_created([r for r in DISBURSEMENT_HOLDS.values() if r["seller_id"] == seller_id])


def plans_of_action_for(action_id):
    return by_created(
        [r for r in PLANS_OF_ACTION.values() if r["enforcement_action_id"] == action_id]
    )


def appeals_for(action_id):
    return by_created(
        [r for r in APPEALS.values() if r["enforcement_action_id"] == action_id]
    )


def snapshots_of(seller_id):
    return by_created([r for r in METRIC_SNAPSHOTS.values() if r["seller_id"] == seller_id])


def links_for_candidate(candidate_id):
    return by_created(
        [r for r in RELATED_ACCOUNT_LINKS.values() if r["candidate_seller_id"] == candidate_id]
    )
