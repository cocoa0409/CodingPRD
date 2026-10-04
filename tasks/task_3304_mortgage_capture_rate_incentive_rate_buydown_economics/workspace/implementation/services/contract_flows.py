"""Sale-contract lifecycle cascades (SCAFFOLD state_machines / endpoint side effects)."""

from db import db, now_iso
from errors import fail
from services import common, calc, selectors
from services import cascades


def buydowns_for_allocation(allocation_id):
    return [r for r in db.buydown_records.values() if r.get("allocation_id") == allocation_id]


def refresh_buydowns(contract, to_booked=False):
    for alloc in common.allocations_of_contract(contract["id"]):
        if alloc.get("bucket") != "RATE_BUYDOWN":
            continue
        for rec in buydowns_for_allocation(alloc["id"]):
            if to_booked and rec.get("record_status") == "DRAFT" and alloc.get(
                "allocation_status"
            ) == "APPLIED":
                rec["record_status"] = "BOOKED"
            calc.buydown_cost_recognition(rec, contract)
            common.touch(rec)


def contract_lock(contract):
    """PENDING -> LOCKED."""
    contract["contract_status"] = "LOCKED"
    common.touch(contract)
    buyer = cascades.buyer_of_contract(contract)
    cascades.set_buyer_status(buyer, "QUALIFIED")
    cascades.refresh_buyer(buyer)
    return contract


def contract_unlock(contract):
    """LOCKED -> PENDING, driven by a lock void or an application expiry."""
    contract["contract_status"] = "PENDING"
    for disc in common.disclosures_of_contract(contract["id"]):
        if disc.get("disclosure_status") == "ACKNOWLEDGED":
            disc["disclosure_status"] = "ISSUED"
            disc["delivery_iso"] = now_iso()
            disc["cure_deadline_iso"] = calc.disclosure_cure_deadline(now_iso())
            common.touch(disc)
    for rec in common.buydowns_of_contract(contract["id"]):
        if rec.get("record_status") == "BOOKED":
            rec["record_status"] = "DRAFT"
        calc.buydown_cost_recognition(rec, contract)
        common.touch(rec)
    # A single unlock event is one mutation of the contract row.
    common.touch(contract)
    cascades.refresh_community_for_contract(contract)
    buyer = cascades.buyer_of_contract(contract)
    cascades.set_buyer_status(buyer, "CONTRACTED")
    cascades.refresh_buyer(buyer)
    return contract


def contract_approve(contract):
    """LOCKED -> APPROVED; every RESERVED allocation becomes APPLIED."""
    contract["contract_status"] = "APPROVED"
    for alloc in common.allocations_of_contract(contract["id"]):
        if alloc.get("allocation_status") == "RESERVED":
            alloc["allocation_status"] = "APPLIED"
            common.touch(alloc)
    common.recompute_contract_incentive_allocated(contract)
    refresh_buydowns(contract, to_booked=True)
    common.touch(contract)
    buyer = cascades.buyer_of_contract(contract)
    cascades.refresh_buyer(buyer)
    cascades.refresh_community_for_contract(contract)
    return contract


def contract_close(contract):
    """APPROVED -> CLOSED; consumes locks and draws units from the commitment."""
    contract["contract_status"] = "CLOSED"
    contract["closed_at"] = now_iso()
    contract["deposit_held_cents"] = int(contract.get("earnest_money_cents") or 0)
    common.touch(contract)

    home = db.home_sites.get(contract.get("home_site_id"))
    if home is not None and home.get("home_site_status") == "UNDER_CONTRACT":
        home["home_site_status"] = "SOLD"
        common.touch(home)

    for lock in common.rate_locks_of_contract(contract["id"]):
        if lock.get("lock_status") != "ACTIVE":
            continue
        lock["lock_status"] = "CONSUMED"
        common.touch(lock)
        commitment = db.forward_commitments.get(lock.get("commitment_id"))
        if commitment is not None:
            cascades.draw_unit(commitment)

    # The recapture window is now measurable: re-recognize every buydown record.
    for rec in common.buydowns_of_contract(contract["id"]):
        calc.buydown_cost_recognition(rec, contract)

    cascades.refresh_community_for_contract(contract)
    buyer = cascades.buyer_of_contract(contract)
    cascades.refresh_buyer(buyer)
    return contract


def _create_forfeiture(contract, statute_class):
    forfeited, refunded, retained = calc.deposit_forfeiture_split(contract, statute_class)
    row = {
        "id": db.new_id(),
        "contract_id": contract["id"],
        "statute_class": statute_class,
        "forfeited_cents": forfeited,
        "refunded_cents": refunded,
        "retained_incentive_cents": retained,
        "forfeiture_status": "PROPOSED",
    }
    common.stamp_new(row)
    db.deposit_forfeitures[row["id"]] = row
    return row


def contract_cancel(contract, reason, statute_class):
    """PENDING/LOCKED -> CANCELLED with the full reversal cascade.

    `statute_class` must be resolved (SELECTOR-03) before any mutation so the
    operation is all-or-nothing.
    """
    forfeited, refunded, retained = calc.deposit_forfeiture_split(contract, statute_class)

    contract["contract_status"] = "CANCELLED"
    contract["cancellation_reason"] = reason
    common.touch(contract)

    home = db.home_sites.get(contract.get("home_site_id"))
    if home is not None and home.get("home_site_status") == "UNDER_CONTRACT":
        home["home_site_status"] = "AVAILABLE"
        common.touch(home)

    for lock in common.rate_locks_of_contract(contract["id"]):
        if lock.get("lock_status") != "ACTIVE":
            continue
        lock["lock_status"] = "VOIDED"
        common.touch(lock)
        commitment = db.forward_commitments.get(lock.get("commitment_id"))
        if commitment is not None:
            cascades.release_unit(commitment)

    for alloc in common.allocations_of_contract(contract["id"]):
        if alloc.get("allocation_status") in ("RESERVED", "APPLIED"):
            alloc["allocation_status"] = "REVERSED"
            common.touch(alloc)
    for rec in common.buydowns_of_contract(contract["id"]):
        if rec.get("record_status") in ("DRAFT", "BOOKED"):
            rec["record_status"] = "REVERSED"
        rec["allowed_buydown_cost_cents"] = 0
        rec["recapture_credit_cents"] = 0
        common.touch(rec)

    common.recompute_contract_incentive_allocated(contract)
    common.touch(contract)

    row = {
        "id": db.new_id(),
        "contract_id": contract["id"],
        "statute_class": statute_class,
        "forfeited_cents": forfeited,
        "refunded_cents": refunded,
        "retained_incentive_cents": retained,
        "forfeiture_status": "PROPOSED",
    }
    common.stamp_new(row)
    db.deposit_forfeitures[row["id"]] = row

    cascades.refresh_community_for_contract(contract)
    buyer = cascades.buyer_of_contract(contract)
    cascades.refresh_buyer(buyer)
    return contract


def contract_reinstate(contract):
    """CANCELLED -> PENDING; voids every proposed settlement."""
    contract["contract_status"] = "PENDING"
    contract["cancellation_reason"] = None
    common.touch(contract)

    for row in common.forfeitures_of_contract(contract["id"]):
        if row.get("forfeiture_status") == "PROPOSED":
            row["forfeiture_status"] = "VOIDED"
            row["refunded_cents"] = int(contract.get("earnest_money_cents") or 0)
            row["forfeited_cents"] = 0
            row["retained_incentive_cents"] = 0
            common.touch(row)

    home = db.home_sites.get(contract.get("home_site_id"))
    if home is not None and home.get("home_site_status") == "AVAILABLE":
        home["home_site_status"] = "UNDER_CONTRACT"
        common.touch(home)

    for alloc in common.allocations_of_contract(contract["id"]):
        if alloc.get("allocation_status") == "REVERSED":
            alloc["allocation_status"] = "PENDING"
            common.touch(alloc)
    common.recompute_contract_incentive_allocated(contract)
    common.touch(contract)

    buyer = cascades.buyer_of_contract(contract)
    cascades.set_buyer_status(buyer, "CONTRACTED")
    cascades.refresh_buyer(buyer)
    cascades.refresh_community_for_contract(contract)
    return contract


# ---------------------------------------------------------------------------
# Community suspension cascade
# ---------------------------------------------------------------------------
def suspend_community(community):
    """ACTIVE/RESTRICTED -> SUSPENDED; force-cancels every PENDING contract."""
    if community.get("program_status") == "SUSPENDED":
        return community
    community["program_status"] = "SUSPENDED"
    common.touch(community)
    pending = [
        c
        for c in common.contracts_of_community(community["id"])
        if c.get("contract_status") == "PENDING"
    ]
    for contract in pending:
        contract_cancel(contract, None, "RESTITUTION_REQUIRED")
    calc.capture_rate_realization(community)
    common.touch(community)
    return community