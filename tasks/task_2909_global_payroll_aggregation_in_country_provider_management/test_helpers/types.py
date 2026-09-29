"""Typed shapes of the eleven resource kinds of the Global Payroll API.

These TypedDicts document the field set the PRD declares for each resource; the
tests use them for readability only, since the API returns plain JSON dicts.
"""

from typing import Any, Dict, List, Optional, TypedDict

Json = Dict[str, Any]
Headers = Dict[str, str]


class CommonFields(TypedDict):
    """PRD 2.4 — ten of the eleven resource kinds carry this full set."""

    id: str
    created_at: str
    updated_at: str
    version: int


COMMON_FIELDS = ("id", "created_at", "updated_at", "version")

# PRD 2.4 — audit evidence items are the single exception: they carry only
# `id` and `created_at`, and neither `updated_at` nor `version` appears.
APPEND_ONLY_FIELDS = ("id", "created_at")


class CountryProfile(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    country_code: str
    local_currency: str
    data_residency_region: str
    statutory_filing_deadline_days: int
    materiality_pct: float
    materiality_floor_minor: int
    penalty_daily_rate_minor: int
    required_filing_types: List[str]
    local_holidays: List[str]
    open_filing_obligation_count: int


class Provider(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    service_scope: List[str]
    data_residency_regions: List[str]
    annual_fee_minor: int
    indemnity_cap_pct: float
    statutory_filing_capable: bool
    status: str
    service_score: float
    score_variant_applied: str
    open_penalty_minor: int


class Engagement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    country_profile_id: str
    provider_id: str
    service_scope: List[str]
    filing_responsibility: str
    data_residency_region: str
    pay_frequency: str
    status: str
    activated_at: Optional[str]
    residency_terms_ref: Optional[str]
    treasury_committed_minor: int
    closed_cycle_count: int
    transition_required: bool
    transition_incoming_provider_id: Optional[str]
    transition_cutover_start_date: Optional[str]
    transition_cutover_end_date: Optional[str]
    transition_parallel_run_cycles: Optional[int]


class PayrollCycle(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    engagement_id: str
    period_label: str
    period_start_date: str
    period_end_date: str
    pay_date: str
    cutoff_lead_working_days: int
    prior_cycle_id: Optional[str]
    input_cutoff_at: str
    status: str
    gross_total_minor: int
    funded_total_minor: int
    filings_confirmed_count: int
    hold_reason: Optional[str]
    input_submitter_user_id: Optional[str]


class InputFile(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    cycle_id: str
    source_system: str
    record_count: int
    gross_declared_minor: int
    country_elements: Dict[str, str]
    residency_region_of_transfer: str
    status: str
    submitted_at: str
    rejection_code: Optional[str]
    validated_record_count: int


class GrossToNetRun(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    cycle_id: str
    input_file_id: str
    gross_minor: int
    net_minor: int
    employer_cost_minor: int
    provider_fee_minor: int
    employee_count: int
    status: str
    variance_basis: Optional[str]
    variance_pct: Optional[float]
    headcount_drift_pct: Optional[float]
    variance_material: bool
    variance_justification: Optional[str]
    return_reason: Optional[str]


class LocalBankAccount(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    engagement_id: str
    account_ref: str
    account_currency: str
    residency_region: str
    daily_cap_minor: int
    settlement_window_hours: int
    buffer_hours: int
    status: str


class FundingInstruction(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    cycle_id: str
    bank_account_id: str
    value_date: str
    funding_currency: str
    fx_rate: float
    requested_local_minor: int
    component_source_minor: Dict[str, int]
    funded_source_minor: int
    window_start_at: str
    window_end_at: str
    status: str
    approver_user_id: Optional[str]
    releaser_user_id: Optional[str]
    recall_reason: Optional[str]


class StatutoryFiling(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    cycle_id: str
    filing_type: str
    responsibility: str
    due_at: str
    status: str
    penalty_status: str
    filed_at: Optional[str]
    submission_ref: Optional[str]
    confirmation_ref: Optional[str]
    late_days: int
    base_penalty_minor: int
    surcharge_minor: int
    total_penalty_minor: int
    provider_share_minor: int
    client_share_minor: int
    penalty_owner: str
    dispute_round: int
    dispute_reason: Optional[str]


class SlaIncident(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    engagement_id: str
    cycle_id: Optional[str]
    incident_type: str
    severity: str
    occurred_at: str
    note: Optional[str]
    status: str
    weight_points: float
    escalation_level: int
    remediation_ref: Optional[str]


class AuditEvidenceItem(TypedDict, total=False):
    """PRD 2.4/3.9 — append-only: no `updated_at` and no `version`."""

    id: str
    created_at: str
    cycle_id: str
    control_ref: str
    evidence_type: str
    payload_hash: str
    recorded_by_role: str
    recorded_by_user_id: str
    sequence_no: int
