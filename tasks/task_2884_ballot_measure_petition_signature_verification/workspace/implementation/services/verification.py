"""Verification-round tallying, round voiding and the line-validation cascade."""

from db import (db, records_of_batch, touch)
from services import calculations as calc
from services import cascades


# ---------------------------------------------------------------------------
# line validation cascade (PRD 3.5)
# ---------------------------------------------------------------------------
def validate_line(record, manual_override):
    """Apply the first-failure-wins cascade to a single signature line."""
    batch = db.batches[record["batch_id"]]
    voter = None
    for candidate in db.voter_records.values():
        if candidate["voter_id_number"] == record["claimed_voter_id_number"]:
            voter = candidate
            break

    # 1. no entry on the roll at all
    if voter is None:
        record["matched_voter_record_id"] = None
        record["validation_status"] = "INVALID_NOT_REGISTERED"
        return
    record["matched_voter_record_id"] = voter["id"]

    # 2. found, but the registration is not ACTIVE
    if voter["registration_status"] != "ACTIVE":
        record["validation_status"] = "INVALID_NOT_REGISTERED"
        return

    # 3. the voter's county is not the batch's county
    if voter["county_id"] != batch["county_id"]:
        record["validation_status"] = "INVALID_WRONG_COUNTY"
        return

    # 4. signature hash mismatch, unless a manual match override is asserted
    if record["signature_hash"] != voter["signature_on_file_hash"]:
        if not manual_override:
            record["validation_status"] = "INVALID_SIGNATURE_MISMATCH"
            return
        record["manual_match_override_applied"] = True

    # 5. duplicate keeper selection runs last
    keeper = calc.duplicate_keeper(record)
    if keeper is not None and keeper["id"] != record["id"]:
        record["validation_status"] = "INVALID_DUPLICATE"
        record["duplicate_of_signature_id"] = keeper["id"]
        return
    record["duplicate_of_signature_id"] = None
    record["validation_status"] = "VALID"


# ---------------------------------------------------------------------------
# tally (PRD 3.6)
# ---------------------------------------------------------------------------
def _touched_batches(rnd):
    batches = []
    seen = set()
    for record in calc.selected_records(rnd):
        if record["batch_id"] in seen:
            continue
        seen.add(record["batch_id"])
        batch = db.batches.get(record["batch_id"])
        if batch is not None:
            batches.append(batch)
    batches.sort(key=lambda b: b["_seq"])
    return batches


def _advanced_status(batch, rnd):
    still_pending = any(r["validation_status"] == "PENDING"
                        for r in records_of_batch(batch["id"]))
    if rnd["round_type"] == "RANDOM_SAMPLE":
        if batch["status"] == "AFFIDAVIT_VERIFIED":
            return "SAMPLED"
        return batch["status"]
    if batch["status"] in ("AFFIDAVIT_VERIFIED", "SAMPLED") and not still_pending:
        return "FULLY_CHECKED"
    return batch["status"]


def tally_round(rnd, examiner_id):
    petition = db.petitions[rnd["petition_id"]]
    standard = db.standards[petition["standard_id"]]

    rnd["sampled_valid_count"] = calc.sampled_valid_count(rnd)
    rnd["validity_rate_bps"] = calc.validity_rate_bps(rnd)
    projected = calc.projection_for_round(rnd, petition, standard)
    rnd["projected_valid_count"] = projected
    rnd["determination"] = calc.determination_for(rnd, projected, petition, standard)
    rnd["tallied_by_examiner_id"] = examiner_id
    rnd["status"] = "CLOSED"

    # batch advancement plus cost accrual — once per batch the round touched
    before = {}
    for batch in _touched_batches(rnd):
        before[batch["id"]] = batch["status"]
        checked = calc.batch_checked_count(batch)
        new_cost = calc.batch_cost_cents(checked, standard)
        delta = new_cost - batch["verification_cost_cents"]
        batch["checked_signature_count"] = checked
        batch["verification_cost_cents"] = new_cost
        petition["verification_cost_accrued_cents"] += delta
        rnd["accrued_cost_cents"] += delta
        batch["status"] = _advanced_status(batch, rnd)
        touch(batch)
    rnd["_batch_status_before"] = before

    petition["projected_valid_count"] = projected
    if rnd["round_type"] in ("FULL_CHECK", "CURE_RECHECK"):
        petition["verified_valid_count"] = projected
    calc.recompute_qualifying_counties(petition)

    determination = rnd["determination"]
    if rnd["round_type"] == "RANDOM_SAMPLE":
        if determination == "SUFFICIENT":
            petition["status"] = "PENDING_CERTIFICATION"
        elif determination == "FULL_CHECK_REQUIRED":
            petition["status"] = "FULL_CHECK"
        else:
            petition["status"] = "CURE_PERIOD" \
                if calc.cure_eligible(petition, standard, projected) else "PENDING_FAILURE"
    elif rnd["round_type"] == "FULL_CHECK":
        if determination == "SUFFICIENT":
            petition["status"] = "PENDING_CERTIFICATION"
        else:
            petition["status"] = "CURE_PERIOD" \
                if calc.cure_eligible(petition, standard, projected) else "PENDING_FAILURE"
    else:  # CURE_RECHECK
        cure_period = db.cure_periods.get(rnd["cure_period_id"])
        if determination == "SUFFICIENT":
            if cure_period is not None:
                cure_period["status"] = "CLOSED_SUFFICIENT"
                touch(cure_period)
            petition["status"] = "PENDING_CERTIFICATION"
        else:
            if cure_period is not None:
                cure_period["status"] = "CLOSED_INSUFFICIENT"
                touch(cure_period)
            petition["status"] = "CURE_PERIOD" \
                if calc.cure_eligible(petition, standard, projected) else "PENDING_FAILURE"

    touch(petition)
    touch(rnd)


# ---------------------------------------------------------------------------
# void (PRD 3.6) — the compensating operation for a round
# ---------------------------------------------------------------------------
def void_round(rnd, reason):
    petition = db.petitions[rnd["petition_id"]]
    was_closed = rnd["status"] == "CLOSED"

    for record in calc.selected_records(rnd):
        record["in_sample"] = False
        record["validated_in_round_id"] = None
        record["validation_status"] = "PENDING"
        touch(record)

    for batch_id, prior_status in (rnd.get("_batch_status_before") or {}).items():
        batch = db.batches.get(batch_id)
        if batch is None:
            continue
        batch["status"] = prior_status
        batch["verification_cost_cents"] = 0
        batch["checked_signature_count"] = calc.batch_checked_count(batch)
        touch(batch)

    petition["verification_cost_accrued_cents"] -= rnd["accrued_cost_cents"]
    rnd["accrued_cost_cents"] = 0
    rnd["voided_reason"] = reason
    rnd["status"] = "VOIDED"
    touch(rnd)

    if was_closed:
        calc.refresh_petition_projection(petition)
    calc.recompute_petition_counts(petition)
    calc.recompute_qualifying_counties(petition)
    remaining_closed = [r for r in db.rounds.values()
                        if r["petition_id"] == petition["id"] and r["status"] == "CLOSED"]
    if not remaining_closed and petition["status"] not in ("CERTIFIED", "FAILED"):
        petition["status"] = "SIGNATURES_FILED"
    touch(petition)
