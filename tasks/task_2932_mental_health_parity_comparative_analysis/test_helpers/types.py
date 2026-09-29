"""TypedDict shapes for every resource the parity API exposes.

Eleven of the twelve resource kinds carry the full system-managed property set
(`id`, `created_at`, `updated_at`, `version`).  A ParticipantNotice is
append-only and carries only `id` and `created_at` — it has neither
`updated_at` nor `version`, and neither field appears in its response payload.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    """The system-managed property set shared by eleven resource kinds."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Administrator(CommonFields, total=False):
    legal_name: str
    contact_email: str
    contractual_production_days: int
    outstanding_request_count: int
    late_request_count: int
    breach_count: int
    regulator_reportable_late_count: int
    cooperation_score: float
    regulatory_basis_cooperation_score: float
    cooperation_status: str


class PlanYear(CommonFields, total=False):
    plan_name: str
    plan_year_label: str
    administrator_id: str
    funding_arrangement: str
    covered_participant_count: int
    remediation_liability_cap_cents: int
    status: str
    compliance_posture: str
    open_violation_count: int
    notified_violation_count: int
    failing_parity_test_count: int
    remediation_liability_cents: int


class BenefitClassification(CommonFields, total=False):
    plan_year_id: str
    benefit_category: str
    network_tier: str
    sub_classification: str
    measurement_period_start: str
    measurement_period_end: str
    mh_su_benefits_covered: bool


class TreatmentLimitation(CommonFields, total=False):
    classification_id: str
    limitation_type: str
    benefit_side: str
    level_value: int
    projected_plan_payments_cents: int
    projected_claims_count: int
    status: str


class ParityTest(CommonFields, total=False):
    classification_id: str
    limitation_type: str
    basis: str
    total_ms_payments_cents: int
    subject_payments_cents: int
    substantially_all_ratio: Optional[float]
    substantially_all_met: bool
    predominant_level: Optional[int]
    mh_level_value: Optional[int]
    result: str
    advisory_only: bool
    status: str


class NqtlItem(CommonFields, total=False):
    plan_year_id: str
    classification_id: str
    nqtl_type: str
    applied_to: str
    description: str
    status: str
    stringency_in_operation_index: float
    stringency_flag: bool
    determination_recorded_by_user_id: Optional[str]


class ComparativeAnalysis(CommonFields, total=False):
    nqtl_item_id: str
    supersedes_analysis_id: Optional[str]
    factor_count: int
    evidentiary_standard_count: int
    stringency_written_finding: str
    stringency_operation_finding: str
    status: str
    revision_round: int
    authored_by_user_id: str
    certified_by_user_id: Optional[str]


class VendorDataRequest(CommonFields, total=False):
    administrator_id: str
    plan_year_id: str
    nqtl_item_id: Optional[str]
    requested_item_count: int
    requested_submission_types: List[str]
    issued_at: str
    due_at: str
    regulatory_due_at: str
    fulfillment_status: str
    escalation_status: str
    validated_submission_count: int
    is_overdue: bool


class DataSubmission(CommonFields, total=False):
    vendor_request_id: str
    classification_id: str
    submission_type: str
    mh_denials: int
    mh_adjudicated_claims: int
    ms_denials: int
    ms_adjudicated_claims: int
    mh_in_network_provider_pct: Optional[float]
    ms_in_network_provider_pct: Optional[float]
    benchmark_note: Optional[str]
    status: str
    rejection_reason: str
    mh_denial_rate: Optional[float]
    ms_denial_rate: Optional[float]
    disparity_ratio: Optional[float]
    as_applied_flag: bool
    network_composition_gap: Optional[float]


class CorrectiveActionPlan(CommonFields, total=False):
    nqtl_item_id: str
    remedy_type: str
    affected_claims_count: int
    average_claim_cents: int
    target_completion_date: str
    reprocessing_liability_cents: int
    status: str
    approved_by_user_id: Optional[str]


class RegulatorRequest(CommonFields, total=False):
    plan_year_id: str
    requested_nqtl_types: List[str]
    request_reference: str
    opened_at: str
    response_due_at: str
    status: str
    regulator_round: int
    requested_item_count: Optional[int]
    covered_item_count: Optional[int]
    completeness_score: Optional[float]
    response_sufficient: Optional[bool]


class ParticipantNotice(TypedDict, total=False):
    """Append-only: `id` and `created_at` only, never `updated_at` or `version`."""

    id: str
    created_at: str
    nqtl_item_id: str
    notice_type: str
    recipient_count: int
    disclosure_summary: str
    issued_at: str
    source: str


class ClockState(TypedDict, total=False):
    current_utc: str
    recomputed_administrator_count: int
    recomputed_plan_year_count: int
