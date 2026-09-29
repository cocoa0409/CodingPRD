"""Domain types for the Certificate of Need Review API.

Status enumerations, the role enumeration and entity TypedDicts, all named
exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────

class UserRole(str, Enum):
    APPLICANT = "Applicant"
    PUBLIC_PARTICIPANT = "PublicParticipant"
    INTAKE_ANALYST = "IntakeAnalyst"
    REVIEW_ANALYST = "ReviewAnalyst"
    DECISION_OFFICER = "DecisionOfficer"
    APPEAL_BOARD_MEMBER = "AppealBoardMember"
    PROGRAM_ADMIN = "ProgramAdmin"


# ─── Enumerations ─────────────────────────────────────

class ServiceType(str, Enum):
    ACUTE_CARE_BEDS = "ACUTE_CARE_BEDS"
    NURSING_HOME_BEDS = "NURSING_HOME_BEDS"
    PSYCHIATRIC_BEDS = "PSYCHIATRIC_BEDS"
    MRI_UNIT = "MRI_UNIT"
    OPEN_HEART_SURGERY = "OPEN_HEART_SURGERY"


class HealthServiceAreaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class StatePlanFormulaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class HearingRoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class OrganizationType(str, Enum):
    HOSPITAL = "HOSPITAL"
    NURSING_FACILITY = "NURSING_FACILITY"
    PHYSICIAN_GROUP = "PHYSICIAN_GROUP"
    OTHER = "OTHER"


class ApplicantStanding(str, Enum):
    GOOD = "GOOD"
    RESTRICTED = "RESTRICTED"
    BARRED = "BARRED"


class LetterOfIntentStatus(str, Enum):
    FILED = "FILED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    CONVERTED = "CONVERTED"
    INELIGIBLE = "INELIGIBLE"


class ReviewDetermination(str, Enum):
    REVIEWABLE = "REVIEWABLE"
    NON_REVIEWABLE = "NON_REVIEWABLE"


class GoverningReviewBasis(str, Enum):
    PROJECT_BASED = "PROJECT_BASED"
    AGGREGATED_24_MONTH = "AGGREGATED_24_MONTH"


class BatchingCycleStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    OPEN_FOR_LOI = "OPEN_FOR_LOI"
    OPEN_FOR_APPLICATIONS = "OPEN_FOR_APPLICATIONS"
    COMPLETENESS_WINDOW = "COMPLETENESS_WINDOW"
    COMPARATIVE_REVIEW = "COMPARATIVE_REVIEW"
    DECIDED = "DECIDED"
    CLOSED = "CLOSED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COMPLETENESS_REVIEW = "COMPLETENESS_REVIEW"
    INCOMPLETE = "INCOMPLETE"
    DEEMED_COMPLETE = "DEEMED_COMPLETE"
    COMPARATIVE_REVIEW = "COMPARATIVE_REVIEW"
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    DENIED = "DENIED"
    REMANDED = "REMANDED"
    WITHDRAWN = "WITHDRAWN"


class DenialReason(str, Enum):
    INSUFFICIENT_NEED = "INSUFFICIENT_NEED"
    FAILED_CRITERIA = "FAILED_CRITERIA"
    APPEAL_REVERSED = "APPEAL_REVERSED"


class CompletenessReviewStatus(str, Enum):
    DEFICIENCY_NOTICE_ISSUED = "DEFICIENCY_NOTICE_ISSUED"
    CURED = "CURED"
    EXPIRED = "EXPIRED"


class CommentStance(str, Enum):
    SUPPORT = "SUPPORT"
    OPPOSE = "OPPOSE"
    NEUTRAL = "NEUTRAL"


class InterventionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class PublicHearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    HELD = "HELD"


class ScoreSheetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"


class CertificateLifecycleStatus(str, Enum):
    ISSUED = "ISSUED"
    IMPLEMENTED = "IMPLEMENTED"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class CertificateExpenditureStatus(str, Enum):
    WITHIN_LIMIT = "WITHIN_LIMIT"
    OVER_LIMIT_PENDING_AMENDMENT = "OVER_LIMIT_PENDING_AMENDMENT"
    LIMIT_BREACHED = "LIMIT_BREACHED"
    LIMIT_AMENDED = "LIMIT_AMENDED"


class ExpenditureBasis(str, Enum):
    CASH = "CASH"
    ACCRUAL = "ACCRUAL"


class ProgressReportStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    BRIEFING = "BRIEFING"
    STAYED = "STAYED"
    HEARD = "HEARD"
    AFFIRMED = "AFFIRMED"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"


class AppealDisposition(str, Enum):
    AFFIRMED = "AFFIRMED"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"


# ─── Entities ─────────────────────────────────────────
# Fourteen of the fifteen record types carry id, created_at, updated_at and
# version (PRD §2.5). PublicComment is the sole exception and carries only
# id and created_at.

class HealthServiceArea(TypedDict):
    id: str
    code: str
    name: str
    population_projection: int
    existing_licensed_beds: int
    approved_unimplemented_beds: int
    capital_authorization_committed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StatePlanFormula(TypedDict):
    id: str
    service_type: str
    effective_from_date: str
    use_rate_per_1000: float
    average_length_of_stay_days: float
    base_target_occupancy_rate: float
    high_volume_target_occupancy_rate: float
    high_volume_bed_threshold: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HearingRoom(TypedDict):
    id: str
    name: str
    seating_capacity: int
    setup_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    legal_name: str
    organization_type: str
    contact_email: str
    standing: str
    compliance_strike_count: int
    created_at: str
    updated_at: str
    version: int


class LetterOfIntent(TypedDict):
    id: str
    applicant_id: str
    hsa_id: str
    batching_cycle_id: str
    service_type: str
    project_description: str
    capital_cost_cents: int
    bed_delta: int
    filed_at: str
    status: str
    project_basis_reviewable: bool
    aggregated_basis_reviewable: bool
    prior_window_loi_count: int
    aggregate_capital_cost_cents: int
    aggregate_bed_delta: int
    governing_review_basis: str
    review_determination: str
    created_at: str
    updated_at: str
    version: int


class BatchingCycle(TypedDict):
    id: str
    hsa_id: str
    formula_id: str
    service_type: str
    status: str
    loi_deadline_at: str
    application_deadline_at: str
    comment_period_closes_at: str
    intervention_deadline_at: str
    completeness_deadline_at: str
    decision_deadline_at: str
    pinned_formula_version: int
    projected_patient_days: float
    provisional_required_beds: float
    selected_target_occupancy_rate: float
    required_beds_final: int
    inventory_beds_at_open: int
    unmet_bed_need_at_open: int
    unallocated_bed_need: int
    reopened_count: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    loi_id: str
    applicant_id: str
    batching_cycle_id: str
    requested_bed_count: int
    projected_capital_cost_cents: int
    narrative: str
    partial_award_acceptable: bool
    status: str
    comparative_score: Optional[float]
    score_sheet_count: int
    allocated_bed_count: int
    denial_reason: Optional[str]
    completeness_round_count: int
    decision_at: Optional[str]
    appeal_window_closes_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompletenessReview(TypedDict):
    id: str
    application_id: str
    round_number: int
    status: str
    deficiency_items: List[str]
    cure_deadline_at: str
    issued_by_user_id: str
    cure_response: Optional[str]
    cured_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PublicComment(TypedDict):
    """Append-only public record row: only id and created_at are carried."""
    id: str
    application_id: str
    commenter_user_id: str
    commenter_display_name: str
    stance: str
    body: str
    filed_at: str
    created_at: str


class Intervention(TypedDict):
    id: str
    application_id: str
    affected_party_applicant_id: str
    grounds: str
    requested_hearing: bool
    status: str
    filed_at: str
    decided_by_user_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PublicHearing(TypedDict):
    id: str
    batching_cycle_id: str
    hearing_room_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    occupancy_start_at: str
    status: str
    attendee_count: Optional[int]
    transcript_reference: Optional[str]
    reschedule_count: int
    created_at: str
    updated_at: str
    version: int


class ScoreSheet(TypedDict):
    id: str
    application_id: str
    reviewer_user_id: str
    need_conformity_score: int
    financial_feasibility_score: int
    cost_containment_score: int
    access_underserved_score: int
    quality_record_score: int
    narrative: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    application_id: str
    superseded_certificate_id: Optional[str]
    approved_expenditure_limit_cents: int
    expenditure_ceiling_cents: int
    expenditure_basis: str
    authorized_bed_count: int
    implementation_milestone_date: str
    required_completion_pct_at_milestone: float
    conditions: List[str]
    lifecycle_status: str
    lifecycle_status_before_suspension: Optional[str]
    expenditure_status: str
    cumulative_expenditure_cash_cents: int
    cumulative_expenditure_accrual_cents: int
    latest_completion_pct: float
    extension_days_granted_total: int
    issued_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ProgressReport(TypedDict):
    id: str
    certificate_id: str
    period_end_date: str
    disbursed_cents: int
    obligated_cents: int
    physical_completion_pct: float
    condition_attestations: List[str]
    status: str
    filed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    application_id: str
    appellant_applicant_id: str
    grounds: str
    status: str
    filed_at: str
    litigation_hold_active: bool
    status_before_hold: Optional[str]
    disposition: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
