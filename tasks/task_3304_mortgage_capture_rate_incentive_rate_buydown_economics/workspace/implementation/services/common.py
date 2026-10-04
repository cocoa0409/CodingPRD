"""Shared mutation helpers, cascades and derived-field recomputations."""

from db import (
    db, now_iso, parse_iso, format_iso, plus_days, clock_dt,
    add_days_from_clock, LOCK_BUFFER_DAYS, PRIORITY_ORDER,
)
from errors import fail


# ---------------------------------------------------------------------------
# Row creation / mutation
# ---------------------------------------------------------------------------
def stamp_new(row):
    row["created_at"] = now_iso()
    row["updated_at"] = row["created_at"]
    row["version"] = 1
    # Internal monotone sequence: the logical clock is frozen between writes, so
    # created_at alone cannot order rows created in the same request window.
    row["_seq"] = db.next_seq()
    return row


def dump(row):
    """Project a row for output, dropping server-internal bookkeeping fields."""
    return {key: value for key, value in row.items() if not key.startswith("_")}


def dump_all(rows):
    return [dump(row) for row in rows]


def sort_rows(rows):
    """Default list ordering: creation timestamp ascending, insertion order tie-break."""
    return sorted(rows, key=lambda row: (row.get("created_at") or "", row.get("_seq") or 0))


def save(store_map, row):
    """Persist a row, refreshing updated_at and incrementing version."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    store_map[row["id"]] = row
    return row


def touch(row):
    """Mutate a row in place (same store map) and bump its bookkeeping."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


# ---------------------------------------------------------------------------
# Clocks a row can live on
# ---------------------------------------------------------------------------
def stored_quantifiers(name, store_map):
    def fn(entity_id):
        return store_map.get(entity_id)
    return fn


# ---------------------------------------------------------------------------
# Derived recomputations
# ---------------------------------------------------------------------------
def community_of(contract):
    home = db.home_sites.get(contract.get("home_site_id"))
    if home is None:
        return None
    return db.communities.get(home.get("community_id"))


def contracts_of_community(community_id):
    out = []
    for contract in db.contracts.values():
        home = db.home_sites.get(contract.get("home_site_id"))
        if home is not None and home.get("community_id") == community_id:
            out.append(contract)
    return out


def applications_of_contract(contract_id):
    return [a for a in db.loan_applications.values() if a.get("contract_id") == contract_id]


def rate_locks_of_contract(contract_id):
    locks = []
    for app in applications_of_contract(contract_id):
        locks.extend(locks_of_application(app["id"]))
    return locks


def locks_of_application(application_id):
    return [l for l in db.rate_locks.values() if l.get("application_id") == application_id]


def allocations_of_contract(contract_id):
    return [a for a in db.incentive_allocations.values() if a.get("contract_id") == contract_id]


def buydowns_of_contract(contract_id):
    return [b for b in db.buydown_records.values() if b.get("contract_id") == contract_id]


def disclosures_of_contract(contract_id):
    return [d for d in db.disclosures.values() if d.get("contract_id") == contract_id]


def forfeitures_of_contract(contract_id):
    return [f for f in db.deposit_forfeitures.values() if f.get("contract_id") == contract_id]


def contracts_of_buyer(buyer_id):
    return [c for c in db.contracts.values() if c.get("buyer_id") == buyer_id]


def buyer_has_rate_buydown_bearing_contract(buyer_id, exclude_contract_id=None):
    """True when at least one contract of the buyer carries a rate-buydown obligation."""
    for contract in contracts_of_buyer(buyer_id):
        if exclude_contract_id is not None and contract["id"] == exclude_contract_id:
            continue
        if contract_carries_rate_buydown(contract):
            return True
    return False


def contract_carries_rate_buydown(contract):
    for alloc in allocations_of_contract(contract["id"]):
        if alloc.get("bucket") == "RATE_BUYDOWN":
            return True
    for rec in buydowns_of_contract(contract["id"]):
        if rec.get("record_status") in ("DRAFT", "BOOKED"):
            return True
    return False


def has_acknowledged_disclosure(contract_id, disclosure_type):
    for disc in disclosures_of_contract(contract_id):
        if disc.get("disclosure_type") == disclosure_type and disc.get(
            "disclosure_status"
        ) == "ACKNOWLEDGED":
            return True
    return False


def recompute_steering_protection(buyer):
    """True exactly when every rate-buydown-bearing contract has an ACKNOWLEDGED ABA.

    PRD section 2.8 states the rule over "every rate-buydown-bearing contract
    belonging to that buyer" with no contract-status carve-out, so a cancelled
    deal still carries its disclosure obligation.
    """
    ok = True
    for contract in contracts_of_buyer(buyer["id"]):
        if contract_carries_rate_buydown(contract):
            if not has_acknowledged_disclosure(contract["id"], "AFFILIATED_BUSINESS_ARRANGEMENT"):
                ok = False
                break
    buyer["steering_protection_flag"] = ok
    return buyer


def recompute_buyer_total(buyer):
    total = 0
    for contract in contracts_of_buyer(buyer["id"]):
        for alloc in allocations_of_contract(contract["id"]):
            if alloc.get("allocation_status") == "APPLIED":
                total += int(alloc.get("allocation_total_cents") or 0)
        for rec in buydowns_of_contract(contract["id"]):
            if rec.get("record_status") == "BOOKED":
                total += int(rec.get("allowed_buydown_cost_cents") or 0)
    buyer["total_incentive_received_cents"] = total
    return buyer


def recompute_contract_incentive_allocated(contract):
    total = 0
    for alloc in allocations_of_contract(contract["id"]):
        if alloc.get("allocation_status") == "APPLIED":
            total += int(alloc.get("allocation_total_cents") or 0)
    contract["incentive_allocated_cents"] = total
    return contract


def recompute_incentive_budget(contract):
    community = community_of(contract)
    if community is None:
        contract["incentive_budget_cents"] = 0
    else:
        contract["incentive_budget_cents"] = (
            int(community.get("price_reduction_cap_cents") or 0)
            + int(community.get("closing_cost_cap_cents") or 0)
            + int(community.get("rate_buydown_cap_cents") or 0)
        )
    return contract


def recompute_commitment_counters(commitment):
    commitment["units_available"] = (
        int(commitment.get("committed_units") or 0)
        - int(commitment.get("units_drawn") or 0)
        + int(commitment.get("units_released") or 0)
    )
    return commitment