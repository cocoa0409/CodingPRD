"""Resource representations.  Field sets follow the entity tables exactly."""

from decimal import Decimal


def _num(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _pick(row, names):
    out = {}
    for name in names:
        out[name] = _num(row.get(name))
    return out


COMMON = ("id", "created_at", "updated_at", "version")

ACQUISITION_FIELDS = COMMON + (
    "target_practice_name", "specialty", "structure", "malpractice_policy_form",
    "annual_malpractice_premium_cents", "tail_coverage_months",
    "tail_coverage_required", "tail_premium_cents",
    "trailing_annual_collections_cents", "target_close_on",
    "required_staff_headcount", "retention_pool_total_cents",
    "retention_pool_committed_cents", "retention_pool_available_cents",
    "escrow_total_cents", "escrow_committed_cents", "escrow_available_cents",
    "deal_status", "compliance_clearance", "readiness_posture",
    "purchase_price_cents", "integration_reserve_cents",
    "gross_consideration_cents", "synergy_credit_bps", "synergy_credit_cents",
    "net_consideration_cents", "hr_staffing_coverage_pct", "closed_at",
    "abandoned_reason",
)

PHYSICIAN_FIELDS = COMMON + (
    "acquisition_id", "npi", "full_name", "specialty", "board_certified",
    "state_license_expires_on", "employment_status",
)

OPINION_FIELDS = COMMON + (
    "acquisition_id", "opinion_type", "method", "normalized_ebitda_cents",
    "projection_years", "ebitda_growth_bps", "discount_rate_bps",
    "terminal_growth_bps", "market_multiple_bps", "cr_conclusion",
    "concluded_value_cents", "independence_attested", "effective_on",
    "expires_on", "prepared_by_user_id", "accepted_by_user_id", "status",
    "is_pinned",
)

PLAN_FIELDS = COMMON + (
    "acquisition_id", "physician_id", "model_type", "base_salary_cents",
    "conversion_factor_cents_per_wrvu", "threshold_wrvu",
    "projected_annual_wrvu", "includes_referral_credit", "stark_exception",
    "fmv_justification_on_file", "projected_total_cash_comp_cents",
    "comp_per_wrvu_cents", "benchmark_basis", "benchmark_percentile",
    "actual_ytd_wrvu", "months_elapsed", "comp_true_up_cents",
    "returned_count", "status", "approved_by_user_id", "executed_at",
)

CONTRACT_FIELDS = COMMON + (
    "acquisition_id", "payer_name", "payer_type", "contract_form",
    "notice_days_required", "effective_on", "terminates_on",
    "annual_revenue_share_bps", "committee_slots_per_cycle", "notice_sent_on",
    "consent_received_on", "novation_status",
)

PACKAGE_FIELDS = COMMON + (
    "acquisition_id", "physician_id", "payer_contract_id", "submitted_on",
    "lead_days", "committee_cycle_key", "projected_effective_on",
    "retro_billing_allowed", "status",
)

BATCH_FIELDS = COMMON + (
    "acquisition_id", "batch_label", "source_system", "chart_type",
    "record_count", "contains_minor_records", "youngest_patient_age_years",
    "last_encounter_on", "validated_count", "defect_count",
    "unprocessed_count", "match_rate_bps", "retention_years",
    "legacy_purge_eligible_on", "retry_count", "status",
)

OFFER_FIELDS = COMMON + (
    "acquisition_id", "staff_member_name", "role_code",
    "legacy_annual_wage_cents", "legacy_pto_hours", "credited_service_months",
    "uplift_component_cents", "pto_component_cents", "wage_floor_applied",
    "offered_annual_wage_cents", "retention_bonus_cents", "offer_expires_on",
    "extended_on", "accepted_on", "status",
)

CONVERSION_FIELDS = COMMON + (
    "acquisition_id", "site_name", "conversion_type", "required_notice_count",
    "notified_patient_count", "notices_issued_on", "effective_on",
    "notice_lead_days", "notice_coverage_bps", "provider_based_uplift_bps",
    "attested_on", "status",
)

TASK_FIELDS = COMMON + (
    "acquisition_id", "task_code", "domain", "is_blocking", "due_on",
    "waiver_justification", "failure_reason", "verified_by_user_id", "status",
)

LIABILITY_FIELDS = COMMON + (
    "acquisition_id", "category", "description", "estimated_amount_cents",
    "indemnity_cap_cents", "disposition", "escrowed_amount_cents",
    "disposition_note",
)

# PerformanceReport is append-only: it carries only id and created_at, and
# neither updated_at nor version appears in its representation.
REPORT_FIELDS = (
    "id", "created_at", "acquisition_id", "physician_id",
    "applied_comp_plan_id", "period_start_on", "period_end_on", "actual_wrvu",
    "actual_collections_cents", "true_up_applied_cents",
    "benchmark_percentile_after",
)

FIELDS_BY_KIND = {
    "acquisitions": ACQUISITION_FIELDS,
    "physicians": PHYSICIAN_FIELDS,
    "valuation_opinions": OPINION_FIELDS,
    "compensation_plans": PLAN_FIELDS,
    "payer_contracts": CONTRACT_FIELDS,
    "credentialing_packages": PACKAGE_FIELDS,
    "ehr_migration_batches": BATCH_FIELDS,
    "staff_transition_offers": OFFER_FIELDS,
    "billing_conversions": CONVERSION_FIELDS,
    "readiness_tasks": TASK_FIELDS,
    "liability_items": LIABILITY_FIELDS,
    "performance_reports": REPORT_FIELDS,
}


def dump(row):
    return _pick(row, FIELDS_BY_KIND[row["_kind"]])


def dump_all(rows):
    return [dump(row) for row in rows]
