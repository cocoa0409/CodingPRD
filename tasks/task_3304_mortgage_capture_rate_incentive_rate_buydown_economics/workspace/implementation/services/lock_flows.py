"""Rate-lock, application and disclosure flows plus the clock sweep."""

from datetime import timedelta

from db import (
    db, now_iso, parse_iso, format_iso, plus_days, midnight, add_days_from_clock,
    QUALIFICATION_VALID_DAYS,
)
from errors import fail
from services import common, calc, selectors, cascades
from services import contract_flows


# ---------------------------------------------------------------------------
# Application helpers
# ---------------------------------------------------------------------------
def locks_of_application(application_id):
    return [l for l in db.rate_locks.values() if l.get("application_id") == application_id]


def drift_key(application):
    return (application.get("contract_id"), application.get("lender_entity_code"))


def recompute_drift(application=None, key=None):
    if application is not None:
        key = drift_key(application)
    if key is None:
        return None
    flagged = db.expiry_counts.get(key, 0) >= 3
    if application is not None:
        application["drift_flag"] = flagged
    for app in db.loan_applications.values():
        if drift_key(app) == key:
            app["drift_flag"] = flagged
    return flagged


def bump_expiry_count(application):
    key = drift_key(application)
    db.expiry_counts[key] = db.expiry_counts.get(key, 0) + 1
    return db.expiry_counts[key]


# ---------------------------------------------------------------------------
# Rate lock creation / transitions
# ---------------------------------------------------------------------------
def create_lock(application, commitment, lock_rate_bps, lock_days):
    # A fresh lock covers exactly its original term, so the marginal-tier rule
    # prices zero extra days: lock_cost_cents opens at 0. The original term is
    # retained so later extensions measure against it (PRD section 3.5).
    extension_cost = calc.lock_extension_cost(lock_days, lock_days)
    row = {
        "_original_lock_days": int(lock_days),
        "id": db.new_id(),
        "application_id": application["id"],
        "commitment_id": commitment["id"],
        "lock_rate_bps": int(lock_rate_bps),
        "lock_days": int(lock_days),
        "lock_start_iso": now_iso(),
        "lock_expires_iso": add_days_from_clock(int(lock_days)),
        "relock_fee_cents": 0,
        "relock_count": 0,
        "lock_cost_cents": extension_cost,
        "lock_status": "ACTIVE",
    }
    common.stamp_new(row)
    db.rate_locks[row["id"]] = row
    common.touch(application)
    return row


def void_lock(lock):
    """ACTIVE -> VOIDED with the commitment return and contract-unlock cascade."""
    lock["lock_status"] = "VOIDED"
    common.touch(lock)
    commitment = db.forward_commitments.get(lock.get("commitment_id"))
    if commitment is not None:
        cascades.release_unit(commitment)
    application = db.loan_applications.get(lock.get("application_id"))
    contract = None
    if application is not None:
        contract = db.contracts.get(application.get("contract_id"))
    if contract is not None:
        if contract.get("contract_status") == "LOCKED":
            contract_flows.contract_unlock(contract)
        else:
            cascades.refresh_community_for_contract(contract)
            cascades.refresh_buyer(cascades.buyer_of_contract(contract))
    return lock


def expire_lock(lock):
    """ACTIVE -> EXPIRED (clock-driven) with the contract-unlock cascade."""
    lock["lock_status"] = "EXPIRED"
    common.touch(lock)
    application = db.loan_applications.get(lock.get("application_id"))
    contract = None
    if application is not None:
        contract = db.contracts.get(application.get("contract_id"))
    if contract is not None and contract.get("contract_status") == "LOCKED":
        contract_flows.contract_unlock(contract)
    elif contract is not None:
        cascades.refresh_buyer(cascades.buyer_of_contract(contract))
    return lock


def relock_rate_lock(lock):
    """EXPIRED -> ACTIVE, charging the escalating flat relock fee."""
    application = db.loan_applications.get(lock.get("application_id"))
    commitment = db.forward_commitments.get(lock.get("commitment_id"))
    original_days = int(lock.get("_original_lock_days") or lock.get("lock_days") or 0)
    lock["relock_count"] = int(lock.get("relock_count") or 0) + 1
    lock["relock_fee_cents"] = calc.lock_extension_cost(
        original_days, lock.get("lock_days"), relock_count=lock["relock_count"]
    )
    lock["lock_cost_cents"] = lock["relock_fee_cents"]
    lock["lock_start_iso"] = now_iso()
    lock["lock_expires_iso"] = add_days_from_clock(int(lock.get("lock_days") or 0))
    lock["lock_status"] = "ACTIVE"
    common.touch(lock)

    if commitment is not None:
        commitment["units_drawn"] = int(commitment.get("units_drawn") or 0)
    contract = None
    if application is not None:
        contract = db.contracts.get(application.get("contract_id"))
    if contract is not None and contract.get("contract_status") == "PENDING":
        contract_flows.contract_lock(contract)
    return lock


def extend_lock(lock, new_lock_days):
    original_days = int(lock.get("_original_lock_days") or lock.get("lock_days") or 0)
    lock["lock_days"] = int(new_lock_days)
    lock["lock_expires_iso"] = format_iso(
        midnight(parse_iso(now_iso())) + timedelta(days=int(new_lock_days))
    )
    lock["lock_cost_cents"] = calc.lock_extension_cost(original_days, int(new_lock_days))
    common.touch(lock)
    return lock


# ---------------------------------------------------------------------------
# Application transitions
# ---------------------------------------------------------------------------
def expire_application(application):
    application["application_status"] = "EXPIRED"
    application["qualified_at"] = None
    application["application_expired_at"] = now_iso()
    bump_expiry_count(application)
    recompute_drift(application)
    common.touch(application)
    for lock in locks_of_application(application["id"]):
        if lock.get("lock_status") == "ACTIVE":
            expire_lock(lock)
    contract = db.contracts.get(application.get("contract_id"))
    if contract is not None:
        cascades.refresh_buyer(cascades.buyer_of_contract(contract))
    return application


def deny_application(application):
    application["application_status"] = "DENIED"
    common.touch(application)
    contract = db.contracts.get(application.get("contract_id"))
    buyer = cascades.buyer_of_contract(contract) if contract is not None else None
    if buyer is not None:
        cascades.set_buyer_status(buyer, "QUALIFIED")
        if not cascades.buyer_has_live_application(buyer["id"]):
            cascades.set_buyer_status(buyer, "PROSPECT")
        cascades.refresh_buyer(buyer)
    return application


def withdraw_buyer(buyer):
    buyer["buyer_status"] = "WITHDRAWN"
    common.touch(buyer)
    for contract in common.contracts_of_buyer(buyer["id"]):
        for app in common.applications_of_contract(contract["id"]):
            if app.get("application_status") == "SUBMITTED":
                app["application_status"] = "DENIED"
                common.touch(app)
    cascades.refresh_buyer(buyer)
    return buyer


# ---------------------------------------------------------------------------
# Disclosure transitions
# ---------------------------------------------------------------------------
def lapse_disclosure(disclosure):
    """ISSUED -> CURING (clock-driven); forces the community toward suspension."""
    disclosure["disclosure_status"] = "CURING"
    common.touch(disclosure)
    contract = db.contracts.get(disclosure.get("contract_id"))
    if contract is not None:
        buyer = cascades.buyer_of_contract(contract)
        if buyer is not None:
            buyer["steering_protection_flag"] = False
            common.touch(buyer)
        community = common.community_of(contract)
        if community is not None and community.get("program_status") in ("ACTIVE", "RESTRICTED"):
            contract_flows.suspend_community(community)
    return disclosure


# ---------------------------------------------------------------------------
# The clock sweep (PRD section 2.13)
# ---------------------------------------------------------------------------
def apply_clock_transitions():
    """Apply every clock-driven transition in one pass; never reverses anything."""
    clock = db.clock

    # ForwardCommitment OPEN -> EXPIRED
    for commitment in list(db.forward_commitments.values()):
        if commitment.get("commitment_status") == "OPEN" and parse_iso(
            clock
        ) > parse_iso(commitment.get("commitment_end_iso")):
            commitment["commitment_status"] = "EXPIRED"
            commitment["pair_off_fee_cents"] = calc.pair_off_fee(
                commitment.get("units_available") or 0
            )
            common.touch(commitment)
            for lock in list(db.rate_locks.values()):
                if lock.get("commitment_id") == commitment["id"] and lock.get(
                    "lock_status"
                ) == "ACTIVE":
                    lock["lock_status"] = "VOIDED"
                    common.touch(lock)
                    application = db.loan_applications.get(lock.get("application_id"))
                    cascades.force_waiver_refused(application)
                    contract = (
                        db.contracts.get(application.get("contract_id"))
                        if application is not None
                        else None
                    )
                    if contract is not None and contract.get("contract_status") == "LOCKED":
                        contract_flows.contract_unlock(contract)
            community = db.communities.get(commitment.get("community_id"))
            if community is not None:
                calc.capture_rate_realization(community)
                common.touch(community)

    # LoanApplication QUALIFIED -> EXPIRED
    for application in list(db.loan_applications.values()):
        if application.get("application_status") != "QUALIFIED":
            continue
        horizon_base = parse_iso(application.get("qualified_at") or application.get("updated_at"))
        if horizon_base is None:
            continue
        horizon = horizon_base + timedelta(days=QUALIFICATION_VALID_DAYS)
        if parse_iso(clock) > horizon:
            expire_application(application)

    # RateLock ACTIVE -> EXPIRED
    for lock in list(db.rate_locks.values()):
        if lock.get("lock_status") == "ACTIVE" and parse_iso(clock) > parse_iso(
            lock.get("lock_expires_iso")
        ):
            expire_lock(lock)

    # ABADisclosure ISSUED -> CURING
    for disclosure in list(db.disclosures.values()):
        if disclosure.get("disclosure_status") == "ISSUED" and parse_iso(clock) > parse_iso(
            disclosure.get("cure_deadline_iso")
        ):
            lapse_disclosure(disclosure)

    return None