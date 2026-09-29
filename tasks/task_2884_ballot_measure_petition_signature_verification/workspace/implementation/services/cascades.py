"""Cascading side effects and their compensating operations (PRD 2.9, 3.9)."""

from db import (ACCEPTED_BATCH_STATUSES, MISCONDUCT_SUSPENSION_THRESHOLD, db,
                assignments_of_circulator, batches_of_circulator,
                batches_of_petition, records_of_batch, touch)
from services import calculations as calc


def recompute_petition_ledgers(petition, projection=True, qualifying=True):
    """Recompute every derived counter the PRD lists for cascades."""
    calc.recompute_petition_counts(petition)
    if projection:
        calc.refresh_petition_projection(petition)
    if qualifying:
        calc.recompute_qualifying_counties(petition)
    petition["cure_period_count"] = len(
        [c for c in db.cure_periods.values() if c["petition_id"] == petition["id"]])
    touch(petition)


def void_batch_lines(batch, void_reason):
    """Void every line of the batch not already VOIDED, recording its prior status."""
    count = 0
    for record in records_of_batch(batch["id"]):
        if record["validation_status"] == "VOIDED":
            continue
        record["status_before_void"] = record["validation_status"]
        record["validation_status"] = "VOIDED"
        record["void_reason"] = void_reason
        touch(record)
        count += 1
    return count


def invalidate_batch(batch, void_reason, invalidation_reason=None):
    """Level 2+3 of the cascade: batch to INVALIDATED, its lines to VOIDED."""
    petition = db.petitions.get(batch["petition_id"])
    if batch["status"] != "INVALIDATED":
        batch["status_before_invalidation"] = batch["status"]
        batch["_accepted_before_invalidation"] = batch["accepted_raw_count"]
        if petition is not None:
            petition["verification_cost_accrued_cents"] -= batch["verification_cost_cents"]
        batch["accepted_raw_count"] = 0
        batch["status"] = "INVALIDATED"
    if invalidation_reason is not None:
        batch["invalidation_reason"] = invalidation_reason
    voided = void_batch_lines(batch, void_reason)
    touch(batch)
    return voided


def reinstate_batch(batch, invalidation_reason=None):
    """The compensating operation: byte-identical restoration of both ledgers."""
    petition = db.petitions.get(batch["petition_id"])
    restored_status = batch["status_before_invalidation"] or "RECEIVED"
    for record in records_of_batch(batch["id"]):
        if record["validation_status"] != "VOIDED":
            continue
        if record["void_reason"] != "BATCH_INVALIDATED":
            continue
        record["validation_status"] = record["status_before_void"] or "PENDING"
        record["status_before_void"] = None
        record["void_reason"] = None
        touch(record)
    batch["status"] = restored_status
    batch["status_before_invalidation"] = None
    batch["accepted_raw_count"] = batch.get("_accepted_before_invalidation", 0) or 0
    batch["_accepted_before_invalidation"] = None
    if petition is not None:
        petition["verification_cost_accrued_cents"] += batch["verification_cost_cents"]
    if invalidation_reason is not None:
        batch["invalidation_reason"] = invalidation_reason
    touch(batch)


def suspend_active_assignments(circulator):
    for assignment in assignments_of_circulator(circulator["id"]):
        if assignment["status"] == "ACTIVE":
            assignment["status"] = "SUSPENDED"
            touch(assignment)


def reactivate_suspended_assignments(circulator):
    for assignment in assignments_of_circulator(circulator["id"]):
        if assignment["status"] == "SUSPENDED":
            assignment["status"] = "ACTIVE"
            touch(assignment)


def revoke_cascade(circulator):
    """Level 1..4: assignments, batches, lines, then every affected petition."""
    petition_ids = []
    for assignment in assignments_of_circulator(circulator["id"]):
        if assignment["status"] == "TERMINATED":
            continue
        assignment["status"] = "TERMINATED"
        touch(assignment)
        if assignment["petition_id"] not in petition_ids:
            petition_ids.append(assignment["petition_id"])
    affected = []
    for batch in batches_of_circulator(circulator["id"]):
        if batch["petition_id"] not in petition_ids:
            continue
        if batch["status"] in ("REJECTED_FORMAT", "INVALIDATED"):
            continue
        invalidate_batch(batch, "CIRCULATOR_REVOKED")
        if batch["petition_id"] not in affected:
            affected.append(batch["petition_id"])
    for petition_id in affected:
        petition = db.petitions.get(petition_id)
        if petition is not None:
            recompute_petition_ledgers(petition)


def fraud_substantiated_cascade(referral, circulator):
    """Batch invalidation, line voiding, strike, rescore, suspension."""
    voided = 0
    petition = db.petitions.get(referral["petition_id"])
    if referral["batch_id"]:
        batch = db.batches.get(referral["batch_id"])
        if batch is not None:
            voided = invalidate_batch(batch, "FRAUD_SUBSTANTIATED")
    referral["voided_signature_count"] = voided
    circulator["misconduct_strike_count"] = len(
        [r for r in db.fraud_referrals.values()
         if r["circulator_id"] == circulator["id"] and r["status"] == "SUBSTANTIATED"])
    calc.recompute_credibility(circulator)
    if circulator["misconduct_strike_count"] >= MISCONDUCT_SUSPENSION_THRESHOLD \
            and circulator["registration_status"] == "REGISTERED":
        circulator["registration_status"] = "SUSPENDED"
        suspend_active_assignments(circulator)
    touch(circulator)
    if petition is not None:
        recompute_petition_ledgers(petition)


def substantiated_referral_names_batch(batch_id):
    return any(r["batch_id"] == batch_id and r["status"] == "SUBSTANTIATED"
               for r in db.fraud_referrals.values())
