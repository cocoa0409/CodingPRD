"""Typed shapes for the resources exposed by the programme API.

Every resource except practice-history carries the four common audit fields
``id``, ``created_at``, ``updated_at`` and ``version``; a practice-history row
is immutable once filed and therefore carries only ``id`` and ``created_at``.
Monetary amounts are integer cents, tonnages and percentages are JSON numbers.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing shim for older interpreters
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore

Json = Dict[str, Any]
Headers = Dict[str, str]


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableCommonFields(TypedDict):
    id: str
    created_at: str


class Grower(CommonFields, total=False):
    legal_name: str
    operator_type: str
    tax_id: str
    mailing_state: str
    status: str
    suspension_reason: Optional[str]
    total_enrolled_acres: float
    lifetime_credits_issued: int
    net_paid_cents: int
    outstanding_clawback_cents: int
    reversal_count: int


class Field(CommonFields, total=False):
    grower_id: str
    field_name: str
    boundary_min_x: int
    boundary_min_y: int
    boundary_max_x: int
    boundary_max_y: int
    gross_acres: float
    mapped_acres: float
    soil_group: str
    county_code: str
    status: str
    surveyor_reference: Optional[str]


class PracticeStandard(CommonFields, total=False):
    practice_code: str
    standard_version: int
    additionality_lookback_years: int
    max_prior_adoption_pct: float
    min_documented_years: int
    min_adoption_years: int
    uncertainty_base_pct: float
    sequestration_rate_per_acre: float
    modeled_baseline_rate_per_acre: float
    buffer_base_pct: float
    telemetry_required: bool
    effective_from: str
    status: str


class PracticeHistory(ImmutableCommonFields, total=False):
    field_id: str
    crop_year: int
    practice_code: str
    adopted: bool
    evidence_source: str
    acres: float
    observed_emissions_per_acre: float


class Enrollment(CommonFields, total=False):
    grower_id: str
    field_id: str
    practice_standard_id: str
    practice_code: str
    pinned_standard_version: int
    commitment_years: int
    start_crop_year: int
    enrolled_acres: float
    payment_model: str
    per_acre_rate_cents: Optional[int]
    per_credit_share_pct: Optional[float]
    prior_adoption_pct: Optional[float]
    additionality_score: Optional[float]
    documented_years: Optional[int]
    status: str
    permanence_status: str
    screening_decision_admin_id: Optional[str]
    baseline_approval_admin_id: Optional[str]
    rejection_reason: Optional[str]
    missing_items: Optional[List[str]]
    exit_reason: Optional[str]
    requested_exit_year: Optional[int]
    exit_fee_cents: Optional[int]
    terminated_effective_year: Optional[int]
    accrued_payment_cents: int
    credits_issued_total: int


class Baseline(CommonFields, total=False):
    enrollment_id: str
    method: str
    qualifying_years: Optional[int]
    historical_mean_rate: Optional[float]
    baseline_emissions_t: float
    uncertainty_pct: float
    status: str
    approved_by_admin_id: Optional[str]
    rejection_note: Optional[str]


class DataPacket(CommonFields, total=False):
    enrollment_id: str
    crop_year: int
    source: str
    reported_acres: float
    measured_value: float
    coverage_pct: float
    qc_score: Optional[float]
    qc_status: str
    completeness_status: str
    flag_reason: Optional[str]
    correction_count: int


class QuantificationRun(CommonFields, total=False):
    enrollment_id: str
    baseline_id: str
    crop_year: int
    method: str
    verified_acres: float
    mean_coverage_pct: Optional[float]
    adoption_factor: Optional[float]
    sampling_uncertainty_pct: Optional[float]
    gross_removals_t: float
    uncertainty_deduction_t: float
    net_removals_t: float
    packet_count: int
    status: str
    revision_count: int


class VerificationBody(CommonFields, total=False):
    name: str
    accreditation_id: str
    accredited_practices: List[str]
    max_concurrent_visits: int
    status: str


class Verification(CommonFields, total=False):
    quantification_run_id: str
    verification_body_id: str
    sample_pct: float
    site_visit_start: Optional[str]
    site_visit_end: Optional[str]
    opinion: Optional[str]
    restated_removals_t: Optional[float]
    material_discrepancy_pct: Optional[float]
    findings_note: Optional[str]
    resample_count: int
    status: str


class CreditBatch(CommonFields, total=False):
    enrollment_id: str
    quantification_run_id: str
    supersedes_batch_id: Optional[str]
    vintage_year: int
    gross_credits: int
    buffer_pct: float
    buffer_credits: int
    issued_credits: int
    risk_tier: str
    serial_start: int
    serial_end: int
    issuance_status: str
    registry_status: str
    registry_account_ref: Optional[str]
    retirement_beneficiary: Optional[str]
    cancellation_reason: Optional[str]


class BufferAccount(CommonFields, total=False):
    pool_code: str
    balance_credits: int
    contributed_total: int
    drawn_total: int
    released_total: int
    unbacked_reversal_credits: int
    outstanding_issued_credits: int
    min_reserve_ratio: float
    required_reserve_credits: int
    next_serial_number: int
    pool_status: str


class ReversalEvent(CommonFields, total=False):
    enrollment_id: str
    credit_batch_id: str
    reversal_type: str
    affected_acres: float
    detected_crop_year: int
    affected_credits: Optional[int]
    buffer_draw_credits: Optional[int]
    unbacked_credits: Optional[int]
    grower_clawback_cents: Optional[int]
    status: str
    reported_by_admin_id: str
    assessed_by_admin_id: Optional[str]
    resolution_note: Optional[str]


class GrowerPayment(CommonFields, total=False):
    enrollment_id: str
    credit_batch_id: Optional[str]
    crop_year: int
    payment_model: str
    payable_acres: Optional[float]
    gross_amount_cents: int
    holdback_pct: float
    holdback_cents: int
    net_amount_cents: int
    status: str
    paid_at: Optional[str]
