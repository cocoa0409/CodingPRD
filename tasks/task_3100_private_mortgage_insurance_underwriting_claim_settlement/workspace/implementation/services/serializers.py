"""Resource presenters.

Every field name below is read from SCAFFOLD section 1.1 (entity table) and the
PRD prose; nothing is invented. Computed fields that are absent until a later
event are emitted as null (PRD 3.3: verified_property_value_cents and
verified_loan_amount_cents are null at issuance; PRD 3.7: a claim's
curtailment_rate_applied, settlement_option_kind and settlement_amount_cents are
absent at filing).
"""

from common import json_number


def master_policy(row):
    return {
        "id": row["id"],
        "policy_number": row["policy_number"],
        "anniversary_utc": row["anniversary_utc"],
        "coverage_percent_default": row["coverage_percent_default"],
        "delegated_curtailment_rate": json_number(row["delegated_curtailment_rate"]),
        "nondelagated_curtailment_rate": json_number(row["nondelagated_curtailment_rate"]),
        "ltv_variance_tolerance": json_number(row["ltv_variance_tolerance"]),
        "servicer_loss_mitigation_standard": row["servicer_loss_mitigation_standard"],
        "rescission_relief_cycles": row["rescission_relief_cycles"],
        "min_third_party_net_bps": row["min_third_party_net_bps"],
        "two_year_effective_flag": row["two_year_effective_flag"],
        "exposure_contribution_rate": json_number(row["exposure_contribution_rate"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def rate_card(row):
    return {
        "id": row["id"],
        "master_policy_id": row["master_policy_id"],
        "credit_grade": row["credit_grade"],
        "ltv_band": row["ltv_band"],
        "coverage_percent": row["coverage_percent"],
        "premium_plan": row["premium_plan"],
        "rate_bps": row["rate_bps"],
        "min_borrower_reserves_months": row["min_borrower_reserves_months"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def reinsurance_treaty(row):
    return {
        "id": row["id"],
        "treaty_number": row["treaty_number"],
        "inception_utc": row["inception_utc"],
        "expiration_utc": row["expiration_utc"],
        "retention_per_claim_cents": row["retention_per_claim_cents"],
        "exhaustion_per_claim_cents": row["exhaustion_per_claim_cents"],
        "aggregate_ceded_cap_cents": row["aggregate_ceded_cap_cents"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def servicer(row):
    return {
        "id": row["id"],
        "servicer_name": row["servicer_name"],
        "tier": row["tier"],
        "loss_mitigation_capability": row["loss_mitigation_capability"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def lender(row):
    return {
        "id": row["id"],
        "lender_name": row["lender_name"],
        "delegated_underwriting": row["delegated_underwriting"],
        "policy_exposure_cap_cents": row["policy_exposure_cap_cents"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def coverage_application(row):
    return {
        "id": row["id"],
        "lender_id": row["lender_id"],
        "master_policy_id": row["master_policy_id"],
        "rate_card_id": row["rate_card_id"],
        "borrower_reference": row["borrower_reference"],
        "loan_amount_cents": row["loan_amount_cents"],
        "property_value_cents": row["property_value_cents"],
        "credit_grade": row["credit_grade"],
        "coverage_percent": row["coverage_percent"],
        "premium_plan": row["premium_plan"],
        "borrower_paid": row["borrower_paid"],
        "financed_premium": row["financed_premium"],
        "borrower_reserves_months": row["borrower_reserves_months"],
        "county_code": row["county_code"],
        "term_months": row["term_months"],
        "underwriting_path": row["underwriting_path"],
        "submitted_utc": row["submitted_utc"],
        "underwritten_utc": row["underwritten_utc"],
        "resubmission_count": row["resubmission_count"],
        "approved_coverage_percent": row["approved_coverage_percent"],
        "rate_bps_applied": row["rate_bps_applied"],
        "coverage_base_upb_cents": row["coverage_base_upb_cents"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def loan(row):
    return {
        "id": row["id"],
        "application_id": row["application_id"],
        "servicer_id": row["servicer_id"],
        "reinsurance_treaty_id": row["reinsurance_treaty_id"],
        "lender_id": row["lender_id"],
        "master_policy_id": row["master_policy_id"],
        "coverage_percent": row["coverage_percent"],
        "premium_plan": row["premium_plan"],
        "borrower_paid": row["borrower_paid"],
        "underwriting_path": row["underwriting_path"],
        "rate_bps_applied": row["rate_bps_applied"],
        "coverage_base_upb_cents": row["coverage_base_upb_cents"],
        "current_upb_cents": row["current_upb_cents"],
        "current_coverage_base_cents": row["current_coverage_base_cents"],
        "annual_premium_cents": row["annual_premium_cents"],
        "monthly_period_cents": row["monthly_period_cents"],
        "final_period_cents": row["final_period_cents"],
        "single_premium_cents": row["single_premium_cents"],
        "origination_property_value_cents": row["origination_property_value_cents"],
        "verified_property_value_cents": row["verified_property_value_cents"],
        "verified_loan_amount_cents": row["verified_loan_amount_cents"],
        "credit_grade": row["credit_grade"],
        "county_code": row["county_code"],
        "term_months": row["term_months"],
        "approval_credit_grade": row["approval_credit_grade"],
        "coverage_status": row["coverage_status"],
        "termination_reason": row["termination_reason"],
        "cancellation_effective_utc": row["cancellation_effective_utc"],
        "amortization_status": row["amortization_status"],
        "milestone_78_reached_utc": row["milestone_78_reached_utc"],
        "delinquency_streak": row["delinquency_streak"],
        "last_loss_mitigation_deficient_utc": row["last_loss_mitigation_deficient_utc"],
        "rescission_relief_status": row["rescission_relief_status"],
        "rescission_relief_cycle_index": row["rescission_relief_cycle_index"],
        "claim_blocked": row["claim_blocked"],
        "aggregate_ceded_cents": row["aggregate_ceded_cents"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def delinquency_report(row):
    return {
        "id": row["id"],
        "loan_id": row["loan_id"],
        "servicer_id": row["servicer_id"],
        "as_of_period": row["as_of_period"],
        "delinquency_class": row["delinquency_class"],
        "months_delinquent": row["months_delinquent"],
        "loss_mitigation_activities": row["loss_mitigation_activities"],
        "reported_utc": row["reported_utc"],
        "effective_utc": row["effective_utc"],
        "participation_standard_met": row["participation_standard_met"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def cancellation_notice(row):
    return {
        "id": row["id"],
        "loan_id": row["loan_id"],
        "request_kind": row["request_kind"],
        "requested_by_role": row["requested_by_role"],
        "notice_utc": row["notice_utc"],
        "evidence_cents": row["evidence_cents"],
        "applied_utc": row["applied_utc"],
        "refund_cents": row["refund_cents"],
        "effective_utc": row["effective_utc"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def external_report(row):
    return {
        "id": row["id"],
        "loan_id": row["loan_id"],
        "verified_loan_amount_cents": row["verified_loan_amount_cents"],
        "verified_property_value_cents": row["verified_property_value_cents"],
        "post_origination_value_cents": row["post_origination_value_cents"],
        "occupancy_reported": row["occupancy_reported"],
        "independent_validation_completed_utc": row["independent_validation_completed_utc"],
        "validated_ltv": json_number(row["validated_ltv"]),
        "occupancy_materially_differs": row["occupancy_materially_differs"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def curtailment_dispute(row):
    return {
        "id": row["id"],
        "loan_id": row["loan_id"],
        "lender_id": row["lender_id"],
        "target_claim_id": row["target_claim_id"],
        "grounds": row["grounds"],
        "asserted_coverage_percent": row["asserted_coverage_percent"],
        "filed_utc": row["filed_utc"],
        "decision": row["decision"],
        "decision_utc": row["decision_utc"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def claim(row):
    return {
        "id": row["id"],
        "loan_id": row["loan_id"],
        "event_kind": row["event_kind"],
        "event_completed_utc": row["event_completed_utc"],
        "unpaid_principal_cents": row["unpaid_principal_cents"],
        "accrued_interest_cents": row["accrued_interest_cents"],
        "allowable_advances_cents": row["allowable_advances_cents"],
        "gross_proceeds_cents": row["gross_proceeds_cents"],
        "expenses_of_sale_cents": row["expenses_of_sale_cents"],
        "filed_utc": row["filed_utc"],
        "curtailment_rate_applied": json_number(row["curtailment_rate_applied"]),
        "permitted_interest_cents": row["permitted_interest_cents"],
        "permitted_advances_cents": row["permitted_advances_cents"],
        "net_unpaid_balance_cents": row["net_unpaid_balance_cents"],
        "recoverable_amount_cents": row["recoverable_amount_cents"],
        "coverage_ceiling_cents": row["coverage_ceiling_cents"],
        "covered_claim_amount_cents": row["covered_claim_amount_cents"],
        "post_curtailment_cents": row["post_curtailment_cents"],
        "claim_deductible_cents": row["claim_deductible_cents"],
        "net_claim_amount_cents": row["net_claim_amount_cents"],
        "trace_number": row["trace_number"],
        "settlement_option_kind": row["settlement_option_kind"],
        "settlement_amount_cents": row["settlement_amount_cents"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def claim_settlement_option(row):
    return {
        "id": row["id"],
        "claim_id": row["claim_id"],
        "option_kind": row["option_kind"],
        "computed_amount_cents": row["computed_amount_cents"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def reinsurance_cession(row):
    return {
        "id": row["id"],
        "claim_id": row["claim_id"],
        "loan_id": row["loan_id"],
        "treaty_id": row["treaty_id"],
        "ceded_amount_cents": row["ceded_amount_cents"],
        "retained_amount_cents": row["retained_amount_cents"],
        "aggregate_ceded_after_cents": row["aggregate_ceded_after_cents"],
        "status": row["status"],
        "rejected_reason": row["rejected_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def portfolio_snapshot(row):
    return {
        "id": row["id"],
        "snapshot_utc": row["snapshot_utc"],
        "cluster_in_force_threshold_cents": row["cluster_in_force_threshold_cents"],
        "lender_concentration_index": json_number(row["lender_concentration_index"]),
        "geography_totals": row["geography_totals"],
        "aggregate_ceded_cents": row["aggregate_ceded_cents"],
        "segment_statuses": row["segment_statuses"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }