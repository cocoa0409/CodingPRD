"""Domain types: entity TypedDicts, status enums and the role enum.

Derived from the PRD's entity surface (§3) and the role list in §2.1.
Two configuration resources — ProgramTrack and Clinician — deliberately carry
only ``id`` and ``created_at`` (§2.5), so their TypedDicts omit ``updated_at``
and ``version``.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    ENROLLMENT_OPS = "EnrollmentOps"
    CLINICAL_OPS = "ClinicalOps"
    CLINICIAN = "Clinician"
    BILLING_OPS = "BillingOps"
    MEMBER = "Member"
    ELIGIBILITY_SERVICE = "EligibilityService"
    OUTREACH_SERVICE = "OutreachService"
    CLINICAL_REVIEW_SERVICE = "ClinicalReviewService"


# ─── Status enums ─────────────────────────────────────
class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class MemberStatus(str, Enum):
    PENDING_ELIGIBILITY = "PENDING_ELIGIBILITY"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    ENROLLED = "ENROLLED"
    GRADUATED = "GRADUATED"
    DROPPED = "DROPPED"


class EligibilityBasis(str, Enum):
    MSK_FLAG = "MSK_FLAG"
    NO_MSK_FLAG = "NO_MSK_FLAG"
    COVERAGE_TERM = "COVERAGE_TERM"
    DEMOGRAPHICS = "DEMOGRAPHICS"


class FileStatus(str, Enum):
    INGESTED = "INGESTED"
    SCREENED = "SCREENED"
    ASSIGNED = "ASSIGNED"
    CLOSED = "CLOSED"


class EnrollmentStatus(str, Enum):
    PENDING_SCREENING = "PENDING_SCREENING"
    PENDING_CLINICAL_REVIEW = "PENDING_CLINICAL_REVIEW"
    AWAITING_TRANSITION_REVIEW = "AWAITING_TRANSITION_REVIEW"
    ACTIVE = "ACTIVE"
    ACTIVATION_FAILED = "ACTIVATION_FAILED"
    COMPLETED = "COMPLETED"
    DROPPED = "DROPPED"
    TRANSITIONED = "TRANSITIONED"


class ClinicalReviewOutcome(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONDUCTED = "CONDUCTED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class OutreachStatus(str, Enum):
    QUEUED = "QUEUED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class ClinicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LIMITED = "LIMITED"
    DEACTIVATED = "DEACTIVATED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class MeasurementStatus(str, Enum):
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"
    FINALIZED = "FINALIZED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class TransitionStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


# ─── Entity TypedDicts (common_fields: true) ──────────
class ClientAccount(TypedDict):
    id: str
    legal_name: str
    client_type: str
    billing_model: str
    savings_share_rate: float
    expected_monthly_engagement_rate: float
    account_status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    client_account_id: str
    external_member_ref: str
    full_name: str
    date_of_birth: str
    musculo_condition_code: str
    baseline_pain_score: float
    baseline_function_score: float
    red_flag_multipliers: List[float]
    red_flag_weight: float
    coach_escalated: bool
    member_status: str
    eligibility_basis: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EligibilityFile(TypedDict):
    id: str
    client_account_id: str
    file_period: str
    roster_format: str
    file_status: str
    member_row_count: int
    eligible_member_count: int
    ineligible_member_count: int
    screened_member_count: int
    total_monthly_fee_cents: int
    provisional_total_monthly_fee_cents: int
    fee_variance_cents: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    member_id: str
    eligibility_file_id: Optional[str]
    program_track_id: Optional[str]
    enrollment_status: str
    clinical_review_outcome: Optional[str]
    clinical_reviewing_clinician_id: Optional[str]
    review_pending_since: Optional[str]
    enrolled_at: Optional[str]
    enrolled_week: Optional[int]
    completed_week: Optional[int]
    dropout_week: Optional[int]
    transition_reason: Optional[str]
    pending_transition_clinician_id: Optional[str]
    weeks_active: int
    adherence_rate: float
    adherence_scored_through_week: int
    pain_reduction_points: float
    function_gain_points: float
    dropout_risk_score: int
    dropout_risk_as_of_week: int
    coach_escalation_required: bool
    consult_cancellation_count: int
    projected_engagement_milestone: int
    attributed_savings_cents: int
    created_at: str
    updated_at: str
    version: int


class ClinicalReview(TypedDict):
    id: str
    enrollment_id: str
    reviewer_id: str
    reviewed_track_id: Optional[str]
    review_decision: Optional[str]
    review_notes: str
    review_status: str
    review_opened_at: str
    conducted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExerciseSession(TypedDict):
    id: str
    enrollment_id: str
    session_date: str
    session_week: int
    recorded_via: str
    session_status: str
    planned_reps: int
    completed_reps: int
    planned_minutes: int
    completed_minutes: int
    pain_score_before: Optional[float]
    scheduled_send_at: str
    pain_score_after: Optional[float]
    track_restricted: bool
    adherence_numerator: float
    adherence_denominator: float
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict):
    id: str
    enrollment_id: str
    claim_service_date: str
    claim_service_week: int
    claim_severity: str
    amount_cents: int
    claim_source: str
    claim_superseded: bool
    line_instance_version: int
    created_at: str
    updated_at: str
    version: int


class OutreachContact(TypedDict):
    id: str
    enrollment_id: str
    contact_week: int
    channel: str
    contact_occurred_at: Optional[str]
    outreach_status: str
    scheduled_send_at: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    enrollment_id: str
    clinician_id: str
    appointment_date: str
    start_minute: int
    duration_minutes: int
    slot_type: str
    appointment_status: str
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutcomeMeasurement(TypedDict):
    id: str
    enrollment_id: str
    measurement_week: int
    pain_score: float
    function_score: float
    measurement_status: str
    claim_window_rank: int
    window_start_week: int
    window_end_week: int
    baseline_pain_score: float
    baseline_function_score: float
    pain_delta_points: float
    function_delta_points: float
    attributed_savings_cents: int
    created_at: str
    updated_at: str
    version: int


class FeeInvoice(TypedDict):
    id: str
    client_account_id: str
    billing_period: str
    billing_model_snapshot: Optional[str]
    milestone_member_count: int
    milestone_engagement_component_cents: int
    savings_share_component_cents: int
    additional_fee_component_cents: int
    recalculated_component_cents: int
    provisional_amount_cents: int
    final_amount_cents: int
    net_delta_cents: int
    finalized_total_cents: Optional[int]
    invoice_status: str
    created_at: str
    updated_at: str
    version: int


class CareTransition(TypedDict):
    id: str
    enrollment_id: str
    approving_clinician_id: str
    transition_status: str
    transitioned_at: Optional[str]
    handoff_referral_count: int
    created_at: str
    updated_at: str
    version: int


# ─── Entity TypedDicts (common_fields: false) ─────────
# ProgramTrack and Clinician carry ONLY id + created_at — no updated_at, no version.
class ProgramTrack(TypedDict):
    id: str
    track_code: str
    base_fee_per_member_cents: int
    expected_sessions_per_week: int
    pain_reduction_target_points: float
    function_gain_target_points: float
    min_adherence_rate: float
    severity_weights: Dict[str, float]
    created_at: str


class Clinician(TypedDict):
    id: str
    full_name: str
    discipline: str
    license_number: str
    clinician_status: str
    weekly_capacity_slots: int
    weekly_completed_minutes: int
    weekly_scheduled_minutes: int
    created_at: str