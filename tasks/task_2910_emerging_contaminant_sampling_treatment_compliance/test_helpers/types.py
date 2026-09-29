"""Typed shapes for the thirteen resource kinds of the API under test.

Every resource carries `id`, `created_at`, `updated_at` and `version`, so those
four live on a shared base. The remaining keys mirror the field names the PRD
introduces for each workflow; they are advisory typing aids for the test suite,
not a schema the server is asked to satisfy.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Contaminant(CommonFields, total=False):
    code: str
    mcl_ng_per_l: float
    trigger_level_ng_per_l: float
    required_mrl_ng_per_l: float
    hazard_index_member: bool
    hbwc_ng_per_l: Optional[float]
    notification_tier: str


class Laboratory(CommonFields, total=False):
    name: str
    certification_id: str
    certified_methods: List[str]
    lowest_achievable_dl_ng_per_l: float
    certification_expires_on: str
    daily_analysis_capacity: int


class EntryPoint(CommonFields, total=False):
    label: str
    source_type: str
    population_served: int
    served_account_count: int
    annual_billed_kgal: int
    baseline_annual_revenue_cents: int
    monitoring_status: str
    requested_monitoring_status: Optional[str]
    treatment_status: str
    compliance_posture: str
    max_compliance_ratio: float
    hazard_index: float
    accepted_result_count: int
    consecutive_qualifying_quarters: int
    consecutive_invalidated_samples: int
    open_violation_count: int


class Sample(CommonFields, total=False):
    entry_point_id: str
    panel_contaminant_ids: List[str]
    monitoring_period: str
    collected_at: str
    protocol: str
    ptfe_free_kit: bool
    field_blank_included: bool
    preservative_lot: str
    resample_of_sample_id: Optional[str]
    collector_user_id: str
    status: str
    assigned_laboratory_id: Optional[str]
    shipped_at: Optional[str]
    received_at: Optional[str]
    chain_of_custody_intact: Optional[bool]
    field_blank_result_ng_per_l: Optional[float]
    invalidation_reason: Optional[str]
    status_before_invalidation: Optional[str]


class LabResult(CommonFields, total=False):
    sample_id: str
    contaminant_id: str
    laboratory_id: str
    method: str
    reported_ng_per_l: float
    detection_limit_ng_per_l: float
    analyzed_at: str
    censored: bool
    compliance_value_ng_per_l: float
    planning_value_ng_per_l: float
    status: str
    review_note: Optional[str]
    reject_reason_code: Optional[str]


class ComplianceDetermination(CommonFields, total=False):
    entry_point_id: str
    contaminant_id: str
    period_end: str
    lraa_ng_per_l: float
    planning_lraa_ng_per_l: float
    quarters_used: int
    hazard_index: float
    determination: str
    violation_type: str
    status: str
    determined_by_user_id: str
    issued_at: Optional[str]
    rescind_reason: Optional[str]


class PublicNotification(CommonFields, total=False):
    determination_id: str
    tier: str
    required_by_at: str
    status: str
    revision_count: int
    content_elements: List[str]
    delivery_methods: List[str]
    drafted_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    review_note: Optional[str]
    delivery_evidence_ref: Optional[str]
    distributed_at: Optional[str]
    late_by_hours: Optional[int]


class TreatmentEvaluation(CommonFields, total=False):
    entry_point_id: str
    status: str
    mandated: bool
    residuals_budget_cents: int
    residuals_spent_cents: int
    selected_technology: Optional[str]
    decision_note: Optional[str]


class PilotTest(CommonFields, total=False):
    treatment_evaluation_id: str
    technology: str
    window_start_at: str
    window_end_at: str
    ebct_min: float
    lifecycle_cost_cents: int
    capital_cost_estimate_cents: int
    annual_om_estimate_cents: int
    residuals_burden_score: float
    footprint_score: float
    om_complexity_score: float
    status: str
    selected: bool
    influent_ng_per_l: Optional[float]
    effluent_ng_per_l: Optional[float]
    bed_volumes_treated: Optional[float]
    spent_media_kg: Optional[float]
    unmanifested_media_kg: float
    removal_pct: Optional[float]
    lifecycle_cost_score: Optional[float]
    technology_score: Optional[float]


class ResidualsManifest(CommonFields, total=False):
    pilot_test_id: str
    media_type: str
    mass_kg: float
    status: str
    waste_classification: Optional[str]
    leachate_pfas_ng_per_l: Optional[float]
    disposal_method: Optional[str]
    disposal_cost_cents: Optional[int]
    carrier_ref: Optional[str]
    classified_by_user_id: Optional[str]
    void_reason_code: Optional[str]


class CapitalProject(CommonFields, total=False):
    entry_point_id: str
    treatment_evaluation_id: str
    capital_cost_cents: int
    annual_om_cost_cents: int
    served_account_count: int
    annual_billed_kgal: int
    current_annual_revenue_cents: int
    construction_status: str
    funding_status: str
    rate_design: str
    required_disposal_method: str
    concentrate_permit_required: bool
    concentrate_permit_ref: Optional[str]
    funding_awarded_cents: int
    grant_equivalent_cents: int
    loan_principal_cents: int
    recovered_cents: int
    local_share_cents: int
    borrowed_cents: int
    annual_debt_service_cents: int
    base_annual_requirement_cents: int
    provisional_rate_impact_pct: float
    surcharge_bp: int
    final_annual_requirement_cents: int
    rate_impact_pct: float
    uniform_monthly_increase_cents: int
    volumetric_rate_increase_cents_per_kgal: int
    volumetric_monthly_increase_cents: int
    monthly_bill_increase_cents: int


class FundingApplication(CommonFields, total=False):
    capital_project_id: str
    program: str
    amount_requested_cents: int
    disadvantaged_community: bool
    forgiveness_pct: float
    status: str
    awarded_cents: Optional[int]
    forgiven_cents: Optional[int]
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    withdraw_reason: Optional[str]


class CostRecoveryClaim(CommonFields, total=False):
    entry_point_id: str
    capital_project_id: str
    responsible_party_name: str
    investigation_basis: str
    allocation_pct: float
    investigation_cost_cents: int
    claim_basis_cents: int
    status: str
    claimed_cents: Optional[int]
    filed_at: Optional[str]
    settled_at: Optional[str]
    recovered_cents: Optional[int]
    alloc_investigation_cents: Optional[int]
    alloc_capital_cents: Optional[int]
    alloc_om_reserve_cents: Optional[int]
    alloc_rate_stabilization_cents: Optional[int]
    resolution_note: Optional[str]


Payload = Dict[str, Any]
Headers = Dict[str, str]
