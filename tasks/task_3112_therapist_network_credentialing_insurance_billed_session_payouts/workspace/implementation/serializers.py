"""Serialisers: PRD-facing projections of every entity (PRD §2.6)."""
from __future__ import annotations

from store import (
    active_patient_count,
    benefit_status,
    continuity_plan_count,
    enrolled_payer_count,
    license_effective_status,
    open_slot_count,
    payout_balance_cents,
    policy_status,
    refresh_posture,
    visit_count_year,
)
from util import fmt_ts

DT_FIELDS = {
    "onboarded_at",
    "offboarding_requested_on",
    "expires_on",
    "verified_at",
    "effective_on",
    "effective_from",
    "effective_to",
    "scheduled_start",
    "scheduled_end",
    "signed_at",
    "submitted_on",
    "recovery_deadline",
    "period_start",
    "period_end",
    "reassignment_deadline",
}


HIDDEN = {
    "verify_attempt_failed",
    "reset_since_failure",
    "_pending_patient_resp_cents",
    "_pending_payer_paid_cents",
    "_carries_clawback",
}


def _base(row: dict) -> dict:
    out = {}
    for key, value in row.items():
        if key.startswith("_") or key in HIDDEN:
            continue
        if key in DT_FIELDS and value is not None and not isinstance(value, str):
            out[key] = fmt_ts(value)
        else:
            out[key] = value
    return out


def clinician(row: dict) -> dict:
    refresh_posture(row)
    row["active_patient_count"] = active_patient_count(row)
    row["open_slot_count"] = open_slot_count(row)
    row["enrolled_payer_count"] = enrolled_payer_count(row)
    row["payout_balance_cents"] = payout_balance_cents(row)
    row["continuity_plan_count"] = continuity_plan_count(row)
    row["offboarding_requested_on"] = row.get("offboarding_requested_on")
    row.setdefault("pending_clawback_residual_cents", 0)
    row.setdefault("cash_basis_opt_in", False)
    return _base(row)


def license(row: dict) -> dict:
    out = _base(row)
    out["verification_status"] = license_effective_status(row)
    return out


def malpractice_policy(row: dict) -> dict:
    out = _base(row)
    out["policy_status"] = policy_status(row)
    return out


def payer(row: dict) -> dict:
    return _base(row)


def payer_rate(row: dict) -> dict:
    return _base(row)


def payer_enrollment(row: dict) -> dict:
    return _base(row)


def patient(row: dict) -> dict:
    row["benefit_status"] = benefit_status(row)
    row["visit_count_year"] = visit_count_year(row)
    row.setdefault("oop_met_cents", 0)
    return _base(row)


def benefit_verification(row: dict) -> dict:
    return _base(row)


def session(row: dict) -> dict:
    row.setdefault("slot_consumed", False)
    row.setdefault("billing_state", "UNBILLED")
    row.setdefault("claim_id", None)
    return _base(row)


def session_note(row: dict) -> dict:
    return _base(row)


def claim(row: dict) -> dict:
    row.setdefault("assigned_payout_line_id", None)
    row.setdefault("patient_resp_cents", 0)
    row.setdefault("payer_paid_cents", 0)
    row.setdefault("resubmission_count", 0)
    return _base(row)


def payout_batch(row: dict) -> dict:
    row.setdefault("total_gross_cents", 0)
    row.setdefault("total_adjustment_cents", 0)
    row.setdefault("total_net_cents", 0)
    row.setdefault("line_count", 0)
    row.setdefault("supersedes_batch_id", None)
    return _base(row)


def payout_line(row: dict) -> dict:
    return _base(row)


def continuity_plan(row: dict) -> dict:
    return _base(row)


SERIALISERS = {
    "clinicians": clinician,
    "licenses": license,
    "malpractice_policies": malpractice_policy,
    "payers": payer,
    "payer_rates": payer_rate,
    "payer_enrollments": payer_enrollment,
    "patients": patient,
    "benefit_verifications": benefit_verification,
    "sessions": session,
    "session_notes": session_note,
    "claims": claim,
    "payout_batches": payout_batch,
    "payout_lines": payout_line,
    "continuity_plans": continuity_plan,
}


def ser(table_name: str, row: dict):
    fn = SERIALISERS.get(table_name)
    return fn(row) if fn else _base(row)