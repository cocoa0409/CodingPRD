"""Output projections. Field sets follow SCAFFOLD entities exactly."""
from decimal import Decimal

import db
import util
from services import guideline, interest, risk

ARREARS_RECOVERY_PCT = Decimal("0.20")


def _ts(value):
    return util.iso_ts(value) if value is not None else None


def _day(value):
    return util.iso_date(value) if value is not None else None


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def participant(row):
    enf_score, enf_tier, comp_score, comp_tier = risk.scores(row)
    return {
        "id": row["id"],
        "role_type": row["role_type"],
        "full_name": row["full_name"],
        "ssn_last4": row["ssn_last4"],
        "residence_state_code": row["residence_state_code"],
        "employer_name": row["employer_name"],
        "monthly_gross_income_cents": row["monthly_gross_income_cents"],
        "income_verification_source": row["income_verification_source"],
        "supports_second_family": row["supports_second_family"],
        "has_valid_drivers_license": row["has_valid_drivers_license"],
        "locate_status": row["locate_status"],
        "locate_attempt_count": row["locate_attempt_count"],
        "license_suspension_active": row["license_suspension_active"],
        "lien_recorded": row["lien_recorded"],
        "credit_bureau_reported": row["credit_bureau_reported"],
        "enforcement_risk_score": enf_score,
        "enforcement_risk_tier": enf_tier,
        "compromise_risk_score": comp_score,
        "compromise_risk_tier": comp_tier,
        "total_arrears_certified_cents": interest.total_arrears_certified(row["id"]),
        "open_case_count": risk.open_case_count(row["id"]),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def case(row):
    principal = interest.arrears_principal(row["id"])
    assigned = principal if row["tanf_assistance"] else 0
    return {
        "id": row["id"],
        "case_type": row["case_type"],
        "custodial_party_id": row["custodial_party_id"],
        "noncustodial_party_id": row["noncustodial_party_id"],
        "child_count": row["child_count"],
        "tanf_assistance": row["tanf_assistance"],
        "good_cause_claim": row["good_cause_claim"],
        "case_status": row["case_status"],
        "enforcement_posture": row["enforcement_posture"],
        "interstate_role": row["interstate_role"],
        "locate_referral_count": row["locate_referral_count"],
        "arrears_principal_cents": principal,
        "total_charged_principal_cents": row["total_charged_principal_cents"],
        "total_collected_principal_cents": row["total_collected_principal_cents"],
        "interest_collected_cents": row["interest_collected_cents"],
        "interest_written_off_cents": row["interest_written_off_cents"],
        "interest_receivable_cents": interest.interest_receivable(row),
        "assigned_arrears_cents": assigned,
        "unassigned_arrears_cents": principal - assigned,
        "unapplied_credit_cents": row["unapplied_credit_cents"],
        "closed_reason": row["closed_reason"],
        "closed_at": _ts(row["closed_at"]),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def paternity_action(row):
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "method": row["method"],
        "status": row["status"],
        "notary_verified": row["notary_verified"],
        "signed_by_participant_id": row.get("signed_by_participant_id"),
        "aop_signed_at": _ts(row["aop_signed_at"]),
        "rescission_deadline_at": _ts(row["rescission_deadline_at"]),
        "rescission_count": row["rescission_count"],
        "genetic_test_ordered_at": _ts(row["genetic_test_ordered_at"]),
        "collection_appointment_at": _ts(row["collection_appointment_at"]),
        "specimen_collected_at": _ts(row["specimen_collected_at"]),
        "specimen_rejection_count": row["specimen_rejection_count"],
        "chain_of_custody_ok": row["chain_of_custody_ok"],
        "genetic_probability_pct": _num(row["genetic_probability_pct"]),
        "genetic_cost_cents": row["genetic_cost_cents"],
        "genetic_cost_liable_party": row["genetic_cost_liable_party"],
        "established_at": _ts(row["established_at"]),
        "established_method": row["established_method"],
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def order(row):
    monthly = row["monthly_obligation_cents"]
    recovery = util.mul_round_half_up(monthly, ARREARS_RECOVERY_PCT) if monthly else 0
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "order_type": row["order_type"],
        "origin_state_code": row["origin_state_code"],
        "status": row["status"],
        "effective_date": _day(row["effective_date"]),
        "terminated_date": _day(row["terminated_date"]),
        "review_eligible_date": _day(
            util.add_months_date(row["effective_date"], 36)
            if row["effective_date"] is not None else None),
        "requested_monthly_cents": row["requested_monthly_cents"],
        "medical_support_monthly_cents": row["medical_support_monthly_cents"],
        "guideline_monthly_cents": row["guideline_monthly_cents"],
        "guideline_cp_income_cents": row["guideline_cp_income_cents"],
        "guideline_ncp_income_cents": row["guideline_ncp_income_cents"],
        "guideline_basic_obligation_cents": row["guideline_basic_obligation_cents"],
        "guideline_ncp_share_ratio": _num(row["guideline_ncp_share_ratio"]),
        "multi_family_credit_cents": row["multi_family_credit_cents"],
        "imputation_applied": row["imputation_applied"],
        "monthly_obligation_cents": monthly,
        "arrears_recovery_monthly_cents": recovery,
        "deviation_applied": row["deviation_applied"],
        "deviation_requested_cents": row["deviation_requested_cents"],
        "deviation_reason": row["deviation_reason"],
        "deviation_rejection_count": row["deviation_rejection_count"],
        "drafted_by_user_id": row["drafted_by_user_id"],
        "findings_approved_by_user_id": row["findings_approved_by_user_id"],
        "superseded_by_order_id": row["superseded_by_order_id"],
        "next_accrual_due_date": _day(row["next_accrual_due_date"]),
        "vacate_reason": row["vacate_reason"],
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def employer(row):
    return {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "fein": row["fein"],
        "state_code": row["state_code"],
        "pay_frequency": row["pay_frequency"],
        "remittance_fee_cents": row["remittance_fee_cents"],
        "statutory_cap_pct": _num(row["statutory_cap_pct"]),
        "active_iwo_count": row["active_iwo_count"],
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def iwo(row):
    return {
        "id": row["id"],
        "order_id": row["order_id"],
        "employer_id": row["employer_id"],
        "service_status": row["service_status"],
        "remittance_status": row["remittance_status"],
        "jurisdiction_state_code": row["jurisdiction_state_code"],
        "reported_disposable_income_cents": row["reported_disposable_income_cents"],
        "federal_cap_pct": _num(row["federal_cap_pct"]),
        "ccpa_cap_pct": _num(row["ccpa_cap_pct"]),
        "ccpa_cap_amount_cents": row["ccpa_cap_amount_cents"],
        "arrears_recovery_cents": row["arrears_recovery_cents"],
        "requested_amount_cents": row["requested_amount_cents"],
        "withholding_amount_cents": row["withholding_amount_cents"],
        "employer_fee_cents": row["employer_fee_cents"],
        "served_at": _ts(row["served_at"]),
        "first_withholding_due_at": _ts(row["first_withholding_due_at"]),
        "next_remittance_due_at": _ts(row["next_remittance_due_at"]),
        "missed_remittance_count": row["missed_remittance_count"],
        "terminated_reason": row["terminated_reason"],
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def charge(row):
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "order_id": row["order_id"],
        "charge_type": row["charge_type"],
        "period_start_date": _day(row["period_start_date"]),
        "period_end_date": _day(row["period_end_date"]),
        "due_date": _day(row["due_date"]),
        "amount_cents": row["amount_cents"],
        "paid_cents": row["paid_cents"],
        "unpaid_balance_cents": row["unpaid_balance_cents"],
        "interest_accrued_cents": row["interest_accrued_cents"],
        "status": row["status"],
        "created_at": _ts(row["created_at"]),
    }


def payment(row):
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "iwo_id": row["iwo_id"],
        "compromise_offer_id": row["compromise_offer_id"],
        "source": row["source"],
        "amount_cents": row["amount_cents"],
        "received_at": _ts(row["received_at"]),
        "applied_current_cents": row["applied_current_cents"],
        "applied_medical_cents": row["applied_medical_cents"],
        "applied_arrears_cents": row["applied_arrears_cents"],
        "applied_interest_cents": row["applied_interest_cents"],
        "applied_genetic_cost_cents": row["applied_genetic_cost_cents"],
        "unapplied_credit_cents": row["unapplied_credit_cents"],
        "retained_by_state_cents": row["retained_by_state_cents"],
        "disbursed_to_cp_cents": row["disbursed_to_cp_cents"],
        "created_at": _ts(row["created_at"]),
    }


def review(row):
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "order_id": row["order_id"],
        "trigger_type": row["trigger_type"],
        "status": row["status"],
        "current_obligation_snapshot_cents": row["current_obligation_snapshot_cents"],
        "recalculated_guideline_cents": row["recalculated_guideline_cents"],
        "variance_numerator_cents": row["variance_numerator_cents"],
        "substantial_change_met": row["substantial_change_met"],
        "info_request_count": row["info_request_count"],
        "info_requested_reason": row["info_requested_reason"],
        "review_eligible_date": _day(row["review_eligible_date"]),
        "screened_at": _ts(row["screened_at"]),
        "proposed_order_id": row["proposed_order_id"],
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def enforcement_action(row):
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "action_type": row["action_type"],
        "status": row["status"],
        "arrears_certified_snapshot_cents": row["arrears_certified_snapshot_cents"],
        "eligibility_threshold_cents": row["eligibility_threshold_cents"],
        "notice_sent_at": _ts(row["notice_sent_at"]),
        "contest_deadline_at": _ts(row["contest_deadline_at"]),
        "contested_at": _ts(row["contested_at"]),
        "contest_grounds": row["contest_grounds"],
        "review_decision": row["review_decision"],
        "proposed_by_user_id": row["proposed_by_user_id"],
        "review_decided_by_user_id": row["review_decided_by_user_id"],
        "activated_at": _ts(row["activated_at"]),
        "released_at": _ts(row["released_at"]),
        "release_reason": row["release_reason"],
        "remedy_applied": row["remedy_applied"],
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def referral(row):
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "direction": row["direction"],
        "other_state_code": row["other_state_code"],
        "child_home_state_code": row["child_home_state_code"],
        "transmittal_type": row["transmittal_type"],
        "status": row["status"],
        "transmitted_at": _ts(row["transmitted_at"]),
        "ack_due_at": _ts(row["ack_due_at"]),
        "registered_at": _ts(row["registered_at"]),
        "controlling_order_id": row["controlling_order_id"],
        "controlling_order_state_code": row["controlling_order_state_code"],
        "returned_reason": row["returned_reason"],
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }


def offer(row):
    return {
        "id": row["id"],
        "case_id": row["case_id"],
        "status": row["status"],
        "principal_due_snapshot_cents": row["principal_due_snapshot_cents"],
        "interest_due_snapshot_cents": row["interest_due_snapshot_cents"],
        "pre_waiver_total_cents": row["pre_waiver_total_cents"],
        "waiver_tier_pct": _num(row["waiver_tier_pct"]),
        "interest_waiver_cents": row["interest_waiver_cents"],
        "settlement_total_cents": row["settlement_total_cents"],
        "installment_count": row["installment_count"],
        "monthly_installment_cents": row["monthly_installment_cents"],
        "final_installment_cents": row["final_installment_cents"],
        "accepted_at": _ts(row["accepted_at"]),
        "next_installment_due_date": _day(row["next_installment_due_date"]),
        "compliance_payment_count": row["compliance_payment_count"],
        "defaulted_at": _ts(row["defaulted_at"]),
        "completed_at": _ts(row["completed_at"]),
        "created_at": _ts(row["created_at"]),
        "updated_at": _ts(row["updated_at"]),
        "version": row["version"],
    }
