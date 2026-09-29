"""Typed shapes for the Practice Acquisition Integration API resources.

One TypedDict per resource declared by the PRD. Eleven of the twelve resources
carry the common fields `id`, `created_at`, `updated_at` and `version`;
`PerformanceReport` is the declared exception and carries only `id` and
`created_at`, so its TypedDict omits `updated_at` and `version`.
"""

from typing import Any, Dict, List, Optional, TypedDict

# Envelope aliases -----------------------------------------------------------

JsonDict = Dict[str, Any]


class ResponseMeta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ErrorPayload(TypedDict):
    error_id: str
    message: str


# Resources ------------------------------------------------------------------


class Acquisition(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    target_practice_name: str
    specialty: str
    structure: str
    malpractice_policy_form: str
    annual_malpractice_premium_cents: int
    tail_coverage_months: int
    tail_coverage_required: bool
    trailing_annual_collections_cents: int
    target_close_on: str
    required_staff_headcount: int
    deal_status: str
    compliance_clearance: str
    readiness_posture: str
    hr_staffing_coverage_pct: float
    tail_premium_cents: Optional[int]
    purchase_price_cents: Optional[int]
    integration_reserve_cents: Optional[int]
    gross_consideration_cents: Optional[int]
    synergy_credit_bps: Optional[int]
    synergy_credit_cents: Optional[int]
    net_consideration_cents: Optional[int]
    retention_pool_total_cents: int
    retention_pool_committed_cents: int
    retention_pool_available_cents: int
    escrow_total_cents: int
    escrow_committed_cents: int
    escrow_available_cents: int
    closed_at: Optional[str]
    abandoned_reason: Optional[str]


class Physician(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    acquisition_id: str
    npi: str
    full_name: str
    specialty: str
    state_license_expires_on: str
    board_certified: bool
    employment_status: str


class ValuationOpinion(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    acquisition_id: str
    opinion_type: str
    method: str
    status: str
    normalized_ebitda_cents: Optional[int]
    market_multiple_bps: Optional[int]
    projection_years: Optional[int]
    ebitda_growth_bps: Optional[int]
    discount_rate_bps: Optional[int]
    terminal_growth_bps: Optional[int]
    cr_conclusion: Optional[str]
    concluded_value_cents: int
    independence_attested: bool
    prepared_by_user_id: str
    accepted_by_user_id: Optional[str]
    is_pinned: bool
    effective_on: str
    expires_on: str
    review_note: Optional[str]


class CompensationPlan(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    acquisition_id: str
    physician_id: str
    model_type: str
    status: str
    base_salary_cents: int
    conversion_factor_cents_per_wrvu: int
    threshold_wrvu: int
    projected_annual_wrvu: int
    projected_total_cash_comp_cents: int
    comp_per_wrvu_cents: int
    benchmark_basis: str
    benchmark_percentile: float
    includes_referral_credit: bool
    stark_exception: str
    fmv_justification_on_file: bool
    returned_count: int
    actual_ytd_wrvu: int
    months_elapsed: int
    comp_true_up_cents: int
    approved_by_user_id: Optional[str]
    executed_at: Optional[str]


class LiabilityItem(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    acquisition_id: str
    category: str
    description: str
    estimated_amount_cents: int
    indemnity_cap_cents: Optional[int]
    disposition: str
    escrowed_amount_cents: int


class PayerContract(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    acquisition_id: str
    payer_name: str
    payer_type: str
    contract_form: str
    novation_status: str
    notice_days_required: int
    notice_sent_on: Optional[str]
    consent_received_on: Optional[str]
    effective_on: str
    terminates_on: str
    annual_revenue_share_bps: int
    committee_slots_per_cycle: int


class CredentialingPackage(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    acquisition_id: str
    physician_id: str
    payer_contract_id: str
    status: str
    submitted_on: str
    committee_cycle_key: str
    lead_days: int
    projected_effective_on: str
    retro_billing_allowed: bool


class EhrMigrationBatch(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    acquisition_id: str
    batch_label: str
    source_system: str
    chart_type: str
    status: str
    record_count: int
    validated_count: int
    defect_count: int
    unprocessed_count: int
    match_rate_bps: int
    retry_count: int
    last_encounter_on: str
    contains_minor_records: bool
    youngest_patient_age_years: Optional[int]
    retention_years: int
    legacy_purge_eligible_on: str


class StaffTransitionOffer(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    acquisition_id: str
    staff_member_name: str
    role_code: str
    status: str
    legacy_annual_wage_cents: int
    legacy_pto_hours: int
    credited_service_months: int
    uplift_component_cents: int
    pto_component_cents: int
    offered_annual_wage_cents: int
    wage_floor_applied: bool
    retention_bonus_cents: int
    offer_expires_on: str
    extended_on: Optional[str]
    accepted_on: Optional[str]


class BillingConversion(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    acquisition_id: str
    site_name: str
    conversion_type: str
    status: str
    required_notice_count: int
    notified_patient_count: int
    notice_coverage_bps: int
    notices_issued_on: Optional[str]
    notice_lead_days: Optional[int]
    provider_based_uplift_bps: int
    effective_on: str
    attested_on: Optional[str]


class ReadinessTask(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    acquisition_id: str
    task_code: str
    domain: str
    status: str
    is_blocking: bool
    due_on: str
    waiver_justification: Optional[str]
    failure_reason: Optional[str]
    verified_by_user_id: Optional[str]


class PerformanceReport(TypedDict, total=False):
    """Carries only `id` and `created_at` from the common field set."""

    id: str
    created_at: str
    acquisition_id: str
    physician_id: str
    applied_comp_plan_id: str
    period_start_on: str
    period_end_on: str
    actual_wrvu: int
    actual_collections_cents: int
    true_up_applied_cents: int
    benchmark_percentile_after: float


PaginatedList = List[JsonDict]
