"""Serializers for each entity (dicts -> response dicts)."""
from store import fmt_ts


def ser_rate_filing(r):
    return {
        "id": r["id"],
        "state_code": r["state_code"],
        "max_flat_fee_pct": r["max_flat_fee_pct"],
        "max_flat_fee_cap_cents": r["max_flat_fee_cap_cents"],
        "filing_mode": r["filing_mode"],
        "status": r["status"],
        "approved_at": fmt_ts(r["approved_at"]) if r.get("approved_at") else None,
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_fee_config(r):
    return {
        "id": r["id"],
        "state_code": r["state_code"],
        "filing_id": r["filing_id"],
        "flat_fee_pct": r["flat_fee_pct"],
        "flat_fee_cents": r["flat_fee_cents"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_treaty(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "quota_share_pct": r["quota_share_pct"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_cause(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_cohort(r):
    return {
        "id": r["id"],
        "cohort_year": r["cohort_year"],
        "cause_id": r["cause_id"],
        "status": r["status"],
        "premium_pool_cents": r["premium_pool_cents"],
        "fee_retained_cents": r["fee_retained_cents"],
        "reinsurance_ceded_cents": r["reinsurance_ceded_cents"],
        "claims_pot_cents": r["claims_pot_cents"],
        "retained_claims_actual_cents": r["retained_claims_actual_cents"],
        "retained_claims_reserved_cents": r["retained_claims_reserved_cents"],
        "giveback_actual_cents": r["giveback_actual_cents"],
        "giveback_projected_cents": r["giveback_projected_cents"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_policyholder(r):
    return {
        "id": r["id"],
        "email": r["email"],
        "full_name": r["full_name"],
        "state_code": r["state_code"],
        "fraud_strike_count": r["fraud_strike_count"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_quote(r):
    return {
        "id": r["id"],
        "policyholder_id": r["policyholder_id"],
        "coverage_amount_cents": r["coverage_amount_cents"],
        "premium_cents": r["premium_cents"],
        "state_code": r["state_code"],
        "expires_at": fmt_ts(r["expires_at"]),
        "premium_grace_days": r["premium_grace_days"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_application(r):
    return {
        "id": r["id"],
        "policyholder_id": r["policyholder_id"],
        "quote_id": r["quote_id"],
        "checkout_velocity_seconds": r["checkout_velocity_seconds"],
        "device_reuse_count": r["device_reuse_count"],
        "answers_ipa_acknowledged": r["answers_ipa_acknowledged"],
        "behavioral_signal_count": r["behavioral_signal_count"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_policy(r):
    return {
        "id": r["id"],
        "policyholder_id": r["policyholder_id"],
        "quote_id": r["quote_id"],
        "cohort_id": r["cohort_id"],
        "fee_config_id": r["fee_config_id"],
        "annual_premium_cents": r["annual_premium_cents"],
        "premium_paid_cents": r["premium_paid_cents"],
        "premium_outstanding_cents": r["premium_outstanding_cents"],
        "fraud_flag": r["fraud_flag"],
        "cause_id": r["cause_id"],
        "cause_election_version": r["cause_election_version"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_claim(r):
    return {
        "id": r["id"],
        "policy_id": r["policy_id"],
        "video_statement_ref": r["video_statement_ref"],
        "claimed_amount_cents": r["claimed_amount_cents"],
        "fraud_score": r["fraud_score"],
        "payout_cents": r["payout_cents"],
        "reserve_cents": r["reserve_cents"],
        "reinsurance_share_cents": r["reinsurance_share_cents"],
        "denial_reason": r["denial_reason"],
        "denied_by_adjuster_id": r["denied_by_adjuster_id"],
        "appeal_deadline": fmt_ts(r["appeal_deadline"]) if r.get("appeal_deadline") else None,
        "appeal_count": r["appeal_count"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_payment(r):
    return {
        "id": r["id"],
        "claim_id": r["claim_id"],
        "amount_cents": r["amount_cents"],
        "reinsurance_share_cents": r["reinsurance_share_cents"],
        "fee_cents": r["fee_cents"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
    }


def ser_ledger_entry(r):
    return {
        "id": r["id"],
        "policy_id": r["policy_id"],
        "kind": r["kind"],
        "amount_cents": r["amount_cents"],
        "claim_id": r["claim_id"],
        "created_at": fmt_ts(r["created_at"]),
    }


def ser_appeal(r):
    return {
        "id": r["id"],
        "claim_id": r["claim_id"],
        "statement": r["statement"],
        "review_note": r["review_note"],
        "status": r["status"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }
