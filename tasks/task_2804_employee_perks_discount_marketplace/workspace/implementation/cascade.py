"""Shared side effects and the two cascade spines of PRD 2.8.

Cascades are never rollbacks: reinstating a merchant does not un-pause its
offers, un-suspending a storefront does not resurrect voided redemptions, and
releasing a confirmed slot writes an offsetting entry rather than deleting one.
"""
import calc
import clock
import db
import derive


def write_ledger(entry_type, amount_cents, merchant_id, memo,
                 redemption_id=None, placement_slot_id=None,
                 statement_id=None, employer_id=None):
    """Append-only: entries carry only id and created_at (PRD 2.5 / 3.9)."""
    return db.insert(db.ledger_entries, {
        "redemption_id": redemption_id,
        "placement_slot_id": placement_slot_id,
        "statement_id": statement_id,
        "employer_id": employer_id,
        "merchant_id": merchant_id,
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "memo": memo,
    }, versioned=False)


# ---------------------------------------------------------------------------
# Programme spine: membership / storefront -> pending redemptions -> inventory
# ---------------------------------------------------------------------------

def void_redemption(redemption, reason):
    """PENDING -> VOID, releasing the offer's reserved inventory unit."""
    if redemption["verification_status"] != "PENDING":
        return False
    redemption["verification_status"] = "VOID"
    redemption["void_reason"] = reason
    redemption["voided_at"] = clock.now()
    db.touch(redemption)
    offer = db.offers.get(redemption["offer_id"])
    if offer is not None:
        # inventory_reserved and sold_out are derived, but the offer row is
        # touched, so it takes its own updated_at and version bump (PRD 2.8).
        db.touch(offer)
    return True


def void_pending_for_membership(membership, reason):
    count = 0
    for r in db.sorted_rows(db.redemptions.values()):
        if r["membership_id"] == membership["id"] and void_redemption(r, reason):
            count += 1
    return count


def void_pending_for_employer(employer, reason):
    count = 0
    for r in db.sorted_rows(db.redemptions.values()):
        if r["employer_id"] == employer["id"] and void_redemption(r, reason):
            count += 1
    return count


def suspend_membership(membership, reason="MEMBERSHIP_INELIGIBLE"):
    """ELIGIBLE -> SUSPENDED plus the pending-redemption void cascade."""
    if membership["status"] != "ELIGIBLE":
        return False
    membership["status"] = "SUSPENDED"
    db.touch(membership)
    void_pending_for_membership(membership, reason)
    return True


# ---------------------------------------------------------------------------
# Partner spine: merchant -> agreements -> offers -> slots -> ledger
# ---------------------------------------------------------------------------

def release_slot(slot, reason):
    """RESERVED/CONFIRMED -> RELEASED; a confirmed fee is offset, never deleted."""
    if slot["status"] not in ("RESERVED", "CONFIRMED"):
        return False
    was_confirmed = slot["status"] == "CONFIRMED"
    slot["status"] = "RELEASED"
    slot["released_at"] = clock.now()
    slot["release_reason"] = reason
    db.touch(slot)
    if was_confirmed:
        write_ledger(
            "PLACEMENT_FEE_REFUND",
            -int(slot["placement_fee_cents"]),
            slot["merchant_id"],
            "Placement fee refund for released slot %s" % slot["id"],
            placement_slot_id=slot["id"],
        )
    return True


def release_slots_of_offer(offer, reason):
    for slot in db.sorted_rows(db.placement_slots.values()):
        if slot["offer_id"] == offer["id"]:
            release_slot(slot, reason)


def expire_offer(offer, release_reason):
    """DRAFT/PENDING_REVIEW/ACTIVE/PAUSED -> EXPIRED via an agreement cascade."""
    if offer["status"] not in ("DRAFT", "PENDING_REVIEW", "ACTIVE", "PAUSED"):
        return False
    was_live = offer["status"] in ("ACTIVE", "PAUSED")
    offer["status"] = "EXPIRED"
    offer["expired_at"] = clock.now()
    db.touch(offer)
    if was_live:
        release_slots_of_offer(offer, release_reason)
    return True


def terminate_agreement(agreement, reason):
    """ACTIVE -> TERMINATED, heading the partner cascade spine."""
    agreement["status"] = "TERMINATED"
    agreement["terminated_reason"] = reason
    agreement["exclusivity_granted"] = False
    db.touch(agreement)
    for offer in db.sorted_rows(db.offers.values()):
        if offer["agreement_id"] == agreement["id"]:
            expire_offer(offer, "AGREEMENT_TERMINATED")


def pause_offers_for_suspended_merchant(merchant):
    """Each ACTIVE offer is paused; leaving ACTIVE releases its live slots."""
    for offer in db.sorted_rows(db.offers.values()):
        if offer["merchant_id"] != merchant["id"] or offer["status"] != "ACTIVE":
            continue
        offer["status"] = "PAUSED"
        offer["paused_reason"] = "MERCHANT_SUSPENDED"
        db.touch(offer)
        release_slots_of_offer(offer, "OFFER_PAUSED")


def suspend_merchant_if_scored(merchant):
    """PRD 3.8: the threshold is tested only when a fault resolution rescores."""
    score = derive.merchant_failure_score(merchant["id"])
    if score >= calc.MERCHANT_SUSPEND_SCORE and merchant["status"] == "ACTIVE":
        merchant["status"] = "SUSPENDED"
        merchant["suspended_at"] = clock.now()
        db.touch(merchant)
        pause_offers_for_suspended_merchant(merchant)
        return True
    return False


def terminate_merchant(merchant, reason):
    """Four-level cascade; deliberately bypasses the category coverage floor."""
    merchant["status"] = "TERMINATED"
    merchant["terminated_reason"] = reason
    db.touch(merchant)
    for agreement in db.sorted_rows(db.agreements.values()):
        if agreement["merchant_id"] != merchant["id"]:
            continue
        if agreement["status"] not in ("DRAFT", "PROVIDER_PROPOSED",
                                       "MERCHANT_COUNTERED", "ACCEPTED", "ACTIVE"):
            continue
        terminate_agreement(agreement, "MERCHANT_TERMINATED")


# ---------------------------------------------------------------------------
# Dispute resolution: the merchant-fault cascade (PRD 3.8)
# ---------------------------------------------------------------------------

def merchant_fault_cascade(dispute, redemption, credit_cents):
    merchant_id = dispute["merchant_id"]
    statement_id = redemption.get("statement_id")
    employer_id = redemption.get("employer_id")

    # 1. the redemption
    redemption["fulfillment_status"] = "REFUNDED"
    redemption["refunded_at"] = clock.now()
    db.touch(redemption)

    # 2. the ledger
    write_ledger("COMMISSION_REVERSAL", -int(redemption["commission_amount_cents"] or 0),
                 merchant_id, "Commission reversal for redemption %s" % redemption["id"],
                 redemption_id=redemption["id"], statement_id=statement_id,
                 employer_id=employer_id)
    share = int(redemption["employer_share_cents"] or 0)
    if share > 0:
        write_ledger("EMPLOYER_SHARE_REVERSAL", share, merchant_id,
                     "Employer share reversal for redemption %s" % redemption["id"],
                     redemption_id=redemption["id"], statement_id=statement_id,
                     employer_id=employer_id)
    credit = int(credit_cents or 0)
    if credit > 0:
        write_ledger("DISPUTE_CREDIT", -credit, merchant_id,
                     "Goodwill credit for dispute %s" % dispute["id"],
                     redemption_id=redemption["id"], statement_id=statement_id,
                     employer_id=employer_id)
        write_ledger("DISPUTE_CREDIT_RECOVERY", credit, merchant_id,
                     "Goodwill credit recovered for dispute %s" % dispute["id"],
                     redemption_id=redemption["id"], statement_id=statement_id,
                     employer_id=employer_id)

    # 3. the statement
    if statement_id:
        statement = db.statements.get(statement_id)
        if statement is not None and statement["status"] == "FINALIZED":
            statement["status"] = "REOPENED"
            statement["reopened_at"] = clock.now()
            statement["reopen_reason"] = "DISPUTE_REVERSAL"
            db.touch(statement)

    # 4. the partner
    merchant = db.merchants.get(merchant_id)
    if merchant is not None:
        merchant["fault_event_count"] = int(merchant["fault_event_count"]) + 1
        merchant["last_fault_at"] = clock.now()
        db.touch(merchant)
        # 5. the partner's offers and slots
        suspend_merchant_if_scored(merchant)
