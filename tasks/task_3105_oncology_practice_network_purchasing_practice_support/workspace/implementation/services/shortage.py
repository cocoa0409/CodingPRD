"""Shortage allocation, the conservation invariants, and grant consumption.

The waterfall (M1 PRO_RATA_BASELINE, M2 PRIORITY_PATHWAY, M3 EQUAL_SPLIT) and
the two conserved quantities of PRD S2.9 live here:

  Invariant A  sum(allocated_units over non-REVOKED grants) + unallocated_units
               == supply_available_units
  Invariant B  sum(committed_units) + quantity of live orders
               == allocated_units
"""

import db
from utils import half_up, num

LIVE_SHORTAGE_STATUSES = ("REPORTED", "ALLOCATING", "ACTIVE")
LIVE_ORDER_STATUSES = ("SUBMITTED", "CONFIRMED", "BACKORDERED")


def live_shortage_for_product(product_id):
    for shortage in db.where("drug_shortages", drug_product_id=product_id):
        if shortage["status"] in LIVE_SHORTAGE_STATUSES:
            return shortage
    return None


def grants_of(shortage_id):
    return db.where("shortage_allocations", shortage_id=shortage_id)


def committed_grants_of(shortage_id):
    return [
        g
        for g in grants_of(shortage_id)
        if g["status"] in ("GRANTED", "PARTIALLY_COMMITTED", "FULLY_COMMITTED")
    ]


def eligible_practices(network_id):
    return [
        p
        for p in db.where("practices", network_id=network_id)
        if p["affiliation_status"] == "AFFILIATED"
    ]


def uncommitted_units(allocation):
    return int(allocation.get("allocated_units") or 0) - int(allocation.get("committed_units") or 0)


def uncommitted_authorization(allocation):
    return int(allocation.get("consumption_authorization_cents") or 0) - int(
        allocation.get("consumed_authorization_cents") or 0
    )


def refresh_grant_status(allocation):
    if allocation["status"] in ("REVOKED", "EXPIRED"):
        return
    allocated = int(allocation.get("allocated_units") or 0)
    committed = int(allocation.get("committed_units") or 0)
    if committed >= allocated and allocated > 0:
        allocation["status"] = "FULLY_COMMITTED"
    elif committed > 0:
        allocation["status"] = "PARTIALLY_COMMITTED"
    else:
        allocation["status"] = "GRANTED"


def refresh_unclaimed(shortage):
    total = 0
    for grant in grants_of(shortage["id"]):
        if grant["status"] in ("REVOKED", "EXPIRED"):
            continue
        total += max(uncommitted_authorization(grant), 0)
    shortage["unclaimed_authorization_cents"] = total


# ---------------------------------------------------------------------------
# The allocation waterfall


def _pro_rata(practices, supply):
    weights = {p["id"]: int(p.get("drug_shortage_baseline_units") or 0) for p in practices}
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return {p["id"]: 0 for p in practices}
    raw = {}
    quota = {}
    for practice in practices:
        weight = weights[practice["id"]]
        raw[practice["id"]] = num(supply) * num(weight) / num(total_weight)
        quota[practice["id"]] = half_up(raw[practice["id"]])
    remainder = supply - sum(quota.values())
    if remainder > 0:
        order = sorted(
            practices,
            key=lambda p: (-(raw[p["id"]] - int(raw[p["id"]])), p.get("created_at") or "", p.get("_seq", 0)),
        )
        for practice in order[:remainder]:
            quota[practice["id"]] += 1
    elif remainder < 0:
        order = sorted(
            practices,
            key=lambda p: (int(raw[p["id"]]), p.get("created_at") or "", p.get("_seq", 0)),
        )
        needed = -remainder
        for practice in order:
            if needed == 0:
                break
            if quota[practice["id"]] > 0:
                quota[practice["id"]] -= 1
                needed -= 1
    return quota


def _priority_pathway(practices, supply):
    order = sorted(
        practices,
        key=lambda p: (
            -float(p.get("pathway_adherence_pct") or 0),
            p.get("created_at") or "",
            p.get("_seq", 0),
        ),
    )
    remaining = supply
    quota = {}
    for practice in order:
        demand = int(practice.get("drug_shortage_baseline_units") or 0)
        grant = min(demand, remaining)
        quota[practice["id"]] = grant
        remaining -= grant
    return quota


def _equal_split(practices, supply):
    order = sorted(practices, key=lambda p: (p.get("created_at") or "", p.get("_seq", 0)))
    count = len(order)
    if count == 0:
        return {}
    base = supply // count
    extra = supply - base * count
    quota = {}
    for index, practice in enumerate(order):
        quota[practice["id"]] = base + (1 if index < extra else 0)
    return quota


def _allocation_order(practices, method, quota):
    if method == "PRIORITY_PATHWAY":
        return sorted(
            practices,
            key=lambda p: (
                -float(p.get("pathway_adherence_pct") or 0),
                p.get("created_at") or "",
                p.get("_seq", 0),
            ),
        )
    if method == "EQUAL_SPLIT":
        return sorted(practices, key=lambda p: (p.get("created_at") or "", p.get("_seq", 0)))
    return sorted(
        practices,
        key=lambda p: (
            -int(p.get("drug_shortage_baseline_units") or 0),
            p.get("created_at") or "",
            p.get("_seq", 0),
        ),
    )


def allocate(shortage, authorization_map):
    """Run (or re-run) the waterfall. Prior live grants are revoked first, and
    the fresh grants sum to exactly supply_available_units."""
    network = db.get("networks", shortage["network_id"])
    method = shortage.get("allocation_method") or (
        network.get("shortage_allocation_method") if network else None
    )
    if method not in ("PRO_RATA_BASELINE", "PRIORITY_PATHWAY", "EQUAL_SPLIT"):
        method = "PRO_RATA_BASELINE"
    supply = int(shortage.get("supply_available_units") or 0)

    # Re-run path: revoke every prior live grant and release its units.
    for grant in grants_of(shortage["id"]):
        if grant["status"] in ("GRANTED", "PARTIALLY_COMMITTED"):
            grant["status"] = "REVOKED"
            shortage["unallocated_units"] = int(shortage.get("unallocated_units") or 0) + int(
                grant.get("allocated_units") or 0
            )
            db.touch(grant)

    practices = eligible_practices(shortage["network_id"])
    if method == "PRIORITY_PATHWAY":
        quota = _priority_pathway(practices, supply)
    elif method == "EQUAL_SPLIT":
        quota = _equal_split(practices, supply)
    else:
        quota = _pro_rata(practices, supply)

    order = _allocation_order(practices, method, quota)
    epoch_index = int((network or {}).get("allocation_epoch_index") or 0)
    total = 0
    for rank, practice in enumerate(order, start=1):
        units = int(quota.get(practice["id"], 0))
        authorization = int(authorization_map.get(practice["id"], 0) or 0)
        grant = db.create(
            "shortage_allocations",
            {
                "shortage_id": shortage["id"],
                "practice_id": practice["id"],
                "allocated_units": units,
                "consumption_authorization_cents": authorization,
                "consumed_authorization_cents": 0,
                "committed_units": 0,
                "allocation_rank": rank,
                "expires_epoch_index": epoch_index + 1,
                "status": "GRANTED",
            },
        )
        total += units
        db.touch(grant)
    shortage["allocated_units"] = total
    shortage["unallocated_units"] = supply - total
    refresh_unclaimed(shortage)
    return shortage


# ---------------------------------------------------------------------------
# Commitment / release (Invariant B)


def commit(allocation, order):
    quantity = int(order.get("quantity_units") or 0)
    value = int(order.get("extended_cost_cents") or 0)
    allocation["committed_units"] = int(allocation.get("committed_units") or 0) + quantity
    allocation["consumed_authorization_cents"] = int(
        allocation.get("consumed_authorization_cents") or 0
    ) + value
    refresh_grant_status(allocation)
    shortage = db.get("drug_shortages", allocation["shortage_id"])
    if shortage is not None:
        shortage["allocated_units"] = int(shortage.get("allocated_units") or 0) + quantity
        refresh_unclaimed(shortage)
        db.touch(shortage)
    db.touch(allocation)


def release(allocation, order):
    quantity = int(order.get("quantity_units") or 0)
    value = int(order.get("extended_cost_cents") or 0)
    allocation["committed_units"] = max(int(allocation.get("committed_units") or 0) - quantity, 0)
    allocation["consumed_authorization_cents"] = max(
        int(allocation.get("consumed_authorization_cents") or 0) - value, 0
    )
    refresh_grant_status(allocation)
    shortage = db.get("drug_shortages", allocation["shortage_id"])
    if shortage is not None:
        shortage["allocated_units"] = int(shortage.get("allocated_units") or 0) - quantity
        shortage["unallocated_units"] = int(shortage.get("unallocated_units") or 0) + quantity
        refresh_unclaimed(shortage)
        db.touch(shortage)
    db.touch(allocation)


def revoke(grant):
    """Return the grant's entire allocated_units - committed or not - to
    unallocated supply."""
    if grant["status"] == "REVOKED":
        return
    shortage = db.get("drug_shortages", grant["shortage_id"])
    grant["status"] = "REVOKED"
    db.touch(grant)
    if shortage is not None:
        shortage["unallocated_units"] = int(shortage.get("unallocated_units") or 0) + int(
            grant.get("allocated_units") or 0
        )
        refresh_unclaimed(shortage)
        db.touch(shortage)


def restore(grant):
    if grant["status"] != "REVOKED":
        return
    shortage = db.get("drug_shortages", grant["shortage_id"])
    grant["status"] = "GRANTED"
    if int(grant.get("committed_units") or 0) > 0:
        refresh_grant_status(grant)
    db.touch(grant)
    if shortage is not None:
        shortage["unallocated_units"] = int(shortage.get("unallocated_units") or 0) - int(
            grant.get("allocated_units") or 0
        )
        refresh_unclaimed(shortage)
        db.touch(shortage)


def expire_grant(grant):
    if grant["status"] in ("REVOKED", "EXPIRED", "FULLY_COMMITTED"):
        return
    shortage = db.get("drug_shortages", grant["shortage_id"])
    released = uncommitted_units(grant)
    grant["status"] = "EXPIRED"
    db.touch(grant)
    if shortage is not None and released > 0:
        shortage["unallocated_units"] = int(shortage.get("unallocated_units") or 0) + released
        refresh_unclaimed(shortage)
        db.touch(shortage)


def check_invariant_a(shortage):
    live = sum(
        int(g.get("allocated_units") or 0)
        for g in grants_of(shortage["id"])
        if g["status"] != "REVOKED"
    )
    return live + int(shortage.get("unallocated_units") or 0) == int(
        shortage.get("supply_available_units") or 0
    )