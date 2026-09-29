"""
Field inventories for every resource the API exposes.

Each list names the resource-specific fields the API returns, so a test can
assert the full shape of a row without repeating the field names.  The common
fields are kept separate because one resource — the fee disclosure — is an
immutable event row that carries only ``id`` and ``created_at``.
"""

from .constants import COMMON_FIELDS, IMMUTABLE_COMMON_FIELDS

POOLED_PLAN_PROVIDER_FIELDS = [
    "legal_name",
    "ein",
    "fidelity_bond_amount_cents",
    "registration_status",
    "registration_number",
    "registration_effective_date",
    "registered_at",
]

PLAN_DOCUMENT_FIELDS = [
    "pooled_plan_provider_id",
    "plan_name",
    "plan_number",
    "plan_year_end_date",
    "status",
    "effective_date",
    "base_eligibility_min_age",
    "base_eligibility_service_months",
    "base_vesting_schedule",
    "base_match_formula_code",
    "participant_count",
    "cumulative_enrolled_participant_count",
    "transferred_out_participant_count",
    "headcount_control_delta",
    "active_employer_count",
    "suspended_employer_count",
    "compliance_posture",
    "audit_required",
    "total_validated_contributions_cents",
    "aggregate_receivable_cents",
    "total_assets_cents",
    "total_corrections_funded_cents",
    "transferred_out_cents",
    "expense_recovered_cents",
    "contribution_control_delta_cents",
]

SERVICE_PROVIDER_FIELDS = [
    "plan_document_id",
    "legal_name",
    "provider_type",
    "revenue_sharing_bps",
    "direct_fee_cents_per_participant",
    "affiliated_service_provider_id",
    "holds_fiduciary_role",
]

FIDUCIARY_ROLE_ALLOCATION_FIELDS = [
    "plan_document_id",
    "service_provider_id",
    "fiduciary_role",
    "effective_from",
    "effective_to",
    "status",
    "acknowledged_at",
    "acknowledgment_statement",
    "revoked_at",
    "revoked_reason",
]

ADOPTING_EMPLOYER_FIELDS = [
    "plan_document_id",
    "legal_name",
    "ein",
    "election_window_close_date",
    "adoption_status",
    "effective_adoption_date",
    "participant_count",
    "hce_count",
    "nhce_count",
    "benefiting_hce_count",
    "benefiting_nhce_count",
    "hce_avg_deferral_pct",
    "nhce_avg_deferral_pct",
    "is_small_plan",
    "employer_audit_required",
    "contribution_hold",
    "open_correction_count",
    "account_balance_cents",
    "contribution_receivable_cents",
    "revenue_sharing_credit_cents",
    "exited_at",
]

PLAN_DESIGN_ELECTION_FIELDS = [
    "adopting_employer_id",
    "election_sequence",
    "eligibility_min_age",
    "eligibility_service_months",
    "vesting_schedule",
    "match_formula_code",
    "match_tier_1_pct",
    "match_tier_1_limit_pct",
    "match_tier_2_pct",
    "match_tier_2_limit_pct",
    "nondiscrimination_track",
    "status",
    "signatory_name",
    "return_reason",
    "deficiency_code",
    "approved_at",
]

PAYROLL_BATCH_FIELDS = [
    "adopting_employer_id",
    "pay_period_start",
    "pay_period_end",
    "pay_date",
    "withholding_date",
    "payroll_provider_reference",
    "total_eligible_compensation_cents",
    "total_deferral_cents",
    "total_match_cents",
    "total_loan_repayment_cents",
    "participant_line_count",
    "expected_match_cents",
    "batch_total_cents",
    "deposit_rule",
    "deposit_due_date",
    "status",
    "validated_at",
    "reconciliation_note",
]

REMITTANCE_DEPOSIT_FIELDS = [
    "payroll_batch_id",
    "deposit_date",
    "amount_cents",
    "deposit_reference",
    "deposit_status",
    "timeliness_status",
    "business_days_elapsed",
    "late_by_business_days",
    "posted_at",
    "posting_reference",
    "correction_method",
    "recovery_date",
    "actual_investment_return_cents",
    "lost_earnings_cents",
    "restoration_cents",
    "excise_tax_cents",
    "form_5330_reference",
    "funded_at",
    "reversal_reason",
]

COMPLIANCE_TEST_FIELDS = [
    "plan_document_id",
    "adopting_employer_id",
    "test_type",
    "scope",
    "plan_year",
    "status",
    "population_hce_count",
    "population_nhce_count",
    "benefiting_hce_count",
    "benefiting_nhce_count",
    "hce_benefiting_pct",
    "nhce_benefiting_pct",
    "ratio_pct",
    "hce_avg_deferral_pct",
    "nhce_avg_deferral_pct",
    "adp_limit_pct",
    "exemption_applied",
    "run_at",
    "failure_reason",
    "closed_reason",
]

PLAN_FILING_FIELDS = [
    "plan_document_id",
    "plan_year",
    "filing_status",
    "prepared_by_user_id",
    "prepared_at",
    "audit_attested_at",
    "audit_opinion",
    "audit_firm_service_provider_id",
    "employer_data_certified_at",
    "certified_by_user_id",
    "certified_employer_count",
    "late_deposit_schedule_h_line_cents",
    "fidelity_bond_minimum_cents",
    "audit_required",
    "filing_deadline_date",
    "filed_date",
    "is_late_filing",
    "acknowledgment_reference",
]

EXIT_TRANSFER_FIELDS = [
    "adopting_employer_id",
    "exit_type",
    "requested_exit_date",
    "blackout_start_date",
    "blackout_end_date",
    "successor_plan_name",
    "status",
    "transferred_participant_count",
    "gross_account_balance_cents",
    "admin_recovery_cents",
    "flat_exit_fee_cents",
    "deductions_applied_cents",
    "unrecovered_deduction_cents",
    "transfer_amount_cents",
    "settled_amount_cents",
    "approved_at",
    "settled_at",
    "reversal_reason",
]

FEE_DISCLOSURE_FIELDS = [
    "plan_document_id",
    "disclosure_period_start",
    "disclosure_period_end",
    "allocation_method",
    "revenue_sharing_pool_cents",
    "gross_direct_fees_cents",
    "expense_rebate_pct",
    "revenue_sharing_offset_cents",
    "net_plan_expense_cents",
    "total_revenue_sharing_allocated_cents",
    "residual_cents_distributed",
    "allocation_lines",
    "eligible_employer_count",
    "disclosed_at",
]

FEE_DISCLOSURE_ALLOCATION_LINE_FIELDS = [
    "adopting_employer_id",
    "basis_amount",
    "basis_share_pct",
    "credit_cents",
    "residual_awarded",
]

# Resource name -> (resource-specific fields, common fields carried).
RESOURCE_SHAPES = {
    "PooledPlanProvider": (POOLED_PLAN_PROVIDER_FIELDS, COMMON_FIELDS),
    "PlanDocument": (PLAN_DOCUMENT_FIELDS, COMMON_FIELDS),
    "ServiceProvider": (SERVICE_PROVIDER_FIELDS, COMMON_FIELDS),
    "FiduciaryRoleAllocation": (FIDUCIARY_ROLE_ALLOCATION_FIELDS, COMMON_FIELDS),
    "AdoptingEmployer": (ADOPTING_EMPLOYER_FIELDS, COMMON_FIELDS),
    "PlanDesignElection": (PLAN_DESIGN_ELECTION_FIELDS, COMMON_FIELDS),
    "PayrollBatch": (PAYROLL_BATCH_FIELDS, COMMON_FIELDS),
    "RemittanceDeposit": (REMITTANCE_DEPOSIT_FIELDS, COMMON_FIELDS),
    "ComplianceTest": (COMPLIANCE_TEST_FIELDS, COMMON_FIELDS),
    "PlanFiling": (PLAN_FILING_FIELDS, COMMON_FIELDS),
    "ExitTransfer": (EXIT_TRANSFER_FIELDS, COMMON_FIELDS),
    "FeeDisclosure": (FEE_DISCLOSURE_FIELDS, IMMUTABLE_COMMON_FIELDS),
}
