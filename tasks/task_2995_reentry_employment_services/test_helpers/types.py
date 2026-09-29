"""
TypedDict shapes for the Reentry Employment Services API.

Every entity in this API carries the common fields `id`, `created_at`,
`updated_at` and `version`, so each entity TypedDict extends CommonFields.
These are documentation-grade shapes used to keep payload construction and
response reads honest; they are not enforced at runtime.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """The four fields every resource in this API carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Envelope(TypedDict):
    meta: Dict[str, Any]
    response_type: str
    data: Any


class ErrorData(TypedDict):
    error_id: str
    message: str


# ---------------------------------------------------------------------------
# Participant
# ---------------------------------------------------------------------------


class AssessmentDomainScores(TypedDict):
    housing_score: int
    transportation_score: int
    health_score: int
    work_history_score: int
    documentation_score: int


class ParticipantCreate(TypedDict, total=False):
    full_name: str
    facility_name: str
    facility_state: str
    expected_release_date: str
    record_categories: List[str]
    required_document_types: List[str]
    assigned_case_manager_user_id: Optional[str]


class Participant(CommonFields, total=False):
    full_name: str
    facility_name: str
    facility_state: str
    expected_release_date: str
    record_categories: List[str]
    required_document_types: List[str]
    assigned_case_manager_user_id: Optional[str]
    stage: str
    suspension_status: str
    suspension_reason: Optional[str]
    license_relief_status: str
    license_relief_occupation_code: Optional[str]
    petition_rounds_used: int
    release_plan_status: str
    release_plan_revision: int
    housing_plan_type: Optional[str]
    transportation_plan_type: Optional[str]
    health_coverage_target: Optional[str]
    planned_release_date: Optional[str]
    actual_release_date: Optional[str]
    verified_document_types: List[str]
    doc_completeness_pct: float
    assessment_domain_scores: Optional[AssessmentDomainScores]
    barrier_score: Optional[float]
    barrier_tier: Optional[str]
    engagement_posture: str
    exit_reason: Optional[str]
    exit_date: Optional[str]


class ReadinessSummary(TypedDict):
    participant_id: str
    stage: str
    doc_completeness_pct: float
    required_document_count: int
    verified_document_count: int
    barrier_score: Optional[float]
    barrier_tier: Optional[str]
    release_plan_status: str
    readiness_met: bool


# ---------------------------------------------------------------------------
# Supervision case
# ---------------------------------------------------------------------------


class SupervisionCaseCreate(TypedDict, total=False):
    participant_id: str
    officer_user_id: str
    officer_name: str
    supervision_type: str
    expected_discharge_date: Optional[str]


class SupervisionCase(CommonFields, total=False):
    participant_id: str
    officer_user_id: str
    officer_name: str
    supervision_type: str
    expected_discharge_date: Optional[str]
    status: str
    work_authorization_status: str
    authorization_change_count: int
    approved_window_start_minute: Optional[int]
    approved_window_end_minute: Optional[int]


# ---------------------------------------------------------------------------
# Employer partnership and job opening
# ---------------------------------------------------------------------------


class PartnershipCreate(TypedDict, total=False):
    employer_name: str
    industry: str
    max_concurrent_placements: int
    wotc_certified: bool
    excluded_record_categories: List[str]


class EmployerPartnership(CommonFields, total=False):
    employer_name: str
    industry: str
    max_concurrent_placements: int
    wotc_certified: bool
    excluded_record_categories: List[str]
    status: str
    active_placement_count: int
    fidelity_bond_enabled: bool
    bond_coverage_cents: Optional[int]
    bond_effective_date: Optional[str]


class JobOpeningCreate(TypedDict, total=False):
    partnership_id: str
    title: str
    occupation_code: str
    hourly_wage_cents: int
    weekly_hours: int
    openings_count: int
    barred_record_categories: List[str]
    requires_license: bool
    license_occupation_code: Optional[str]
    requires_fidelity_bond: bool
    transit_accessible: bool


class JobOpening(CommonFields, total=False):
    partnership_id: str
    title: str
    occupation_code: str
    hourly_wage_cents: int
    weekly_hours: int
    openings_count: int
    barred_record_categories: List[str]
    requires_license: bool
    license_occupation_code: Optional[str]
    requires_fidelity_bond: bool
    transit_accessible: bool
    status: str
    offered_count: int
    filled_count: int
    remaining_openings: int


class MatchPreview(TypedDict):
    job_opening_id: str
    participant_id: str
    match_score: int
    match_breakdown: Dict[str, int]
    eligible: bool
    blocking_error_id: Optional[str]


# ---------------------------------------------------------------------------
# Readiness sessions and enrollments
# ---------------------------------------------------------------------------


class ReadinessSessionCreate(TypedDict, total=False):
    session_type: str
    coach_user_id: str
    starts_at: str
    ends_at: str
    seat_capacity: int


class ReadinessSession(CommonFields, total=False):
    session_type: str
    coach_user_id: str
    starts_at: str
    ends_at: str
    seat_capacity: int
    status: str
    enrolled_count: int
    remaining_seats: int


class SessionEnrollment(CommonFields, total=False):
    session_id: str
    participant_id: str
    disclosure_script_reviewed: bool
    status: str


# ---------------------------------------------------------------------------
# Placements, shifts
# ---------------------------------------------------------------------------


class PlacementCreate(TypedDict, total=False):
    participant_id: str
    job_opening_id: str
    grant_id: Optional[str]
    subsidy_track: str
    expected_job_opening_version: int
    start_date: str


class Placement(CommonFields, total=False):
    participant_id: str
    job_opening_id: str
    grant_id: Optional[str]
    subsidy_track: str
    start_date: str
    employment_status: str
    bonding_status: str
    schedule_compliance: str
    match_score: int
    match_breakdown: Dict[str, int]
    projected_subsidy_cents: int
    actual_subsidy_cents: int
    disbursed_subsidy_cents: int
    separation_reason: Optional[str]
    separation_date: Optional[str]
    retention_30_outcome: Optional[str]
    retention_60_outcome: Optional[str]
    retention_90_outcome: Optional[str]
    last_retention_check_at: Optional[str]
    recidivism_event: str


class WorkShift(CommonFields, total=False):
    placement_id: str
    starts_at: str
    ends_at: str
    scheduled_hours: float
    status: str
    conflict_reason: Optional[str]


# ---------------------------------------------------------------------------
# Grants and support requests
# ---------------------------------------------------------------------------


class GrantCreate(TypedDict, total=False):
    funder_name: str
    program_year: int
    authorized_cents: int
    allowed_categories: List[str]
    per_participant_cap_cents: int
    retention_benchmark_pct: float


class FunderGrant(CommonFields, total=False):
    funder_name: str
    program_year: int
    authorized_cents: int
    allowed_categories: List[str]
    per_participant_cap_cents: int
    retention_benchmark_pct: float
    committed_cents: int
    disbursed_cents: int
    available_cents: int
    open_request_count: int
    funding_posture: str


class GrantLedger(TypedDict):
    grant_id: str
    authorized_cents: int
    committed_cents: int
    disbursed_cents: int
    available_cents: int
    restricted_floor_cents: int
    funding_posture: str
    open_request_count: int
    deferred_request_count: int


class OutcomeReport(TypedDict):
    grant_id: str
    variant: str
    participants_served: int
    denominator_placements: int
    retained_placements: int
    retention_rate_pct: Optional[float]
    recidivism_rate_pct: Optional[float]
    benchmark_met: bool
    subsidy_disbursed_cents: int
    support_disbursed_cents: int


class LineItemInput(TypedDict, total=False):
    description: str
    unit_cost_cents: int
    quantity: int


class LineItemPriced(TypedDict, total=False):
    description: str
    unit_cost_cents: int
    quantity: int
    line_award_cents: int


class SupportRequestCreate(TypedDict, total=False):
    participant_id: str
    grant_id: str
    category: str
    expected_grant_version: int
    line_items: List[LineItemInput]
    justification: str


class SupportRequest(CommonFields, total=False):
    participant_id: str
    grant_id: str
    category: str
    line_items: List[LineItemPriced]
    justification: str
    requested_cents: int
    admin_fee_cents: int
    total_charge_cents: int
    status: str
    info_rounds_used: int
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]
    review_note: Optional[str]
    settlement_note: Optional[str]
    deferred_at: Optional[str]
    promoted_at: Optional[str]
