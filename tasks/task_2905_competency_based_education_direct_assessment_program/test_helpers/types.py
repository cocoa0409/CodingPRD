"""Domain types for the competency-based education / direct assessment API.

Entity dictionaries, status enumerations and the role enumeration, all named
exactly as the PRD names them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    STUDENT = "Student"
    FACULTY_MENTOR = "FacultyMentor"
    EVALUATOR = "Evaluator"
    INTEGRITY_OFFICER = "IntegrityOfficer"
    FINANCIAL_AID_OFFICER = "FinancialAidOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enumerations ──────────────────────────────────────────────────────

class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class CompetencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CompetencyLevel(str, Enum):
    FOUNDATION = "FOUNDATION"
    CORE = "CORE"
    CAPSTONE = "CAPSTONE"


class BlueprintStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class PassingRule(str, Enum):
    WEIGHTED_ONLY = "WEIGHTED_ONLY"
    WEIGHTED_PLUS_ALL_CRITICAL = "WEIGHTED_PLUS_ALL_CRITICAL"


class EnrollmentStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"
    GRADUATED = "GRADUATED"


class SapStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WARNING = "WARNING"
    PROBATION = "PROBATION"
    DISMISSED = "DISMISSED"


class TermStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class TermCloseOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class MentorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class SelectionMode(str, Enum):
    EXPLICIT = "EXPLICIT"
    AUTO_SELECTED = "AUTO_SELECTED"


class CadenceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    OVERDUE = "OVERDUE"


class EvaluatorStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    PROVISIONAL = "PROVISIONAL"
    SUSPENDED = "SUSPENDED"


class CertificationLevel(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    SENIOR = "SENIOR"


class AttemptStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADJUDICATION = "ADJUDICATION"
    INTEGRITY_HOLD = "INTEGRITY_HOLD"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SCORED_MASTERED = "SCORED_MASTERED"
    SCORED_NOT_MASTERED = "SCORED_NOT_MASTERED"
    VOIDED = "VOIDED"


class ScoreVariant(str, Enum):
    SINGLE_READER_FINAL = "SINGLE_READER_FINAL"
    PROVISIONAL_SINGLE_READER = "PROVISIONAL_SINGLE_READER"
    TWO_READER_MEAN = "TWO_READER_MEAN"
    ADJUDICATED = "ADJUDICATED"


class ScoreStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VOIDED = "VOIDED"


class ScoreVoidedReason(str, Enum):
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ATTEMPT_VOIDED = "ATTEMPT_VOIDED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class CaseOutcome(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class CaseSignalType(str, Enum):
    SHARED_DEVICE = "SHARED_DEVICE"
    DUPLICATE_ARTIFACT = "DUPLICATE_ARTIFACT"
    ATTESTATION_ANOMALY = "ATTESTATION_ANOMALY"
    THIRD_PARTY_REPORT = "THIRD_PARTY_REPORT"


class CaseSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CaseSanction(str, Enum):
    NONE = "NONE"
    ATTEMPT_VOID = "ATTEMPT_VOID"
    TERM_SUSPENSION = "TERM_SUSPENSION"


class PaceBand(str, Enum):
    GOOD = "GOOD"
    WARN = "WARN"
    PROB = "PROB"
    FAIL = "FAIL"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    DISBURSED = "DISBURSED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class HoldReason(str, Enum):
    CREDIT_EQUIVALENCY_SHORTFALL = "CREDIT_EQUIVALENCY_SHORTFALL"
    TERM_CLOSED = "TERM_CLOSED"
    INTEGRITY_REVIEW = "INTEGRITY_REVIEW"


class TranscriptStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class TranscriptPurpose(str, Enum):
    TRANSFER = "TRANSFER"
    INTERNAL = "INTERNAL"
    STUDENT_COPY = "STUDENT_COPY"


class TranscriptVoidedReason(str, Enum):
    UNIT_TOTAL_CHANGED = "UNIT_TOTAL_CHANGED"
    SUPERSEDED = "SUPERSEDED"


# ─── Entity shapes ────────────────────────────────────────────────────────────
# Entities carrying id / created_at / updated_at / version.

class Program(TypedDict):
    id: str
    code: str
    title: str
    status: str
    mastery_threshold_pct: float
    units_per_credit_hour: float
    sap_min_units_per_term: float
    required_unit_total: float
    irr_tolerance_pct: float
    irr_min_paired_reviews: int
    irr_suspend_rate_pct: float
    attempt_cooloff_hours: int
    attempts_before_endorsement: int
    critical_dimension_min_ratio: float
    cadence_gate_overdue_days: int
    blueprint_notice_days: int
    aid_earned_pct_full_threshold: float
    aid_min_credit_equivalency: int
    competency_count: int
    published_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Competency(TypedDict):
    id: str
    program_id: str
    code: str
    title: str
    unit_value: float
    level: str
    mastery_threshold_pct: Optional[float]
    effective_mastery_threshold_pct: float
    prerequisite_competency_id: Optional[str]
    prerequisite_depth: int
    status: str
    effective_blueprint_id: Optional[str]
    mastered_by_student_count: int
    created_at: str
    updated_at: str
    version: int


class RubricDimension(TypedDict):
    code: str
    weight: float
    max_score: float
    critical: bool


class AssessmentBlueprint(TypedDict):
    id: str
    competency_id: str
    version_label: str
    dimensions: List[RubricDimension]
    dimension_count: int
    passing_rule: str
    required_evaluator_count: int
    effective_from_utc: str
    effective_to_utc: Optional[str]
    status: str
    attempts_bound_count: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    program_id: str
    full_name: str
    email: str
    enrollment_status: str
    sap_status: str
    mastered_unit_total: float
    mastered_competency_count: int
    cumulative_credit_equivalency: float
    integrity_strike_count: int
    aid_scheduled_total_cents: int
    aid_retained_total_cents: int
    aid_returned_total_cents: int
    activated_at_utc: Optional[str]
    suspended_at_utc: Optional[str]
    withdrawn_at_utc: Optional[str]
    graduated_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubscriptionTerm(TypedDict):
    id: str
    student_id: str
    term_start_utc: str
    term_end_utc: str
    tuition_cents: int
    status: str
    term_days: int
    attempts_used: int
    units_mastered_in_term: float
    credit_equivalency_earned: int
    activated_at_utc: Optional[str]
    closed_effective_utc: Optional[str]
    attended_days: Optional[int]
    earned_pct: Optional[float]
    institutional_refund_cents: Optional[int]
    net_institutional_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Mentor(TypedDict):
    id: str
    full_name: str
    email: str
    max_caseload: int
    cadence_days: int
    current_caseload: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MentorAssignment(TypedDict):
    id: str
    mentor_id: str
    student_id: str
    cadence_days: int
    selection_mode: str
    assigned_at_utc: str
    last_contact_utc: Optional[str]
    contact_count: int
    next_contact_due_utc: str
    cadence_status: str
    overdue_days: int
    endorsed_competency_ids: List[str]
    endorsement_count: int
    status: str
    ended_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Evaluator(TypedDict):
    id: str
    full_name: str
    email: str
    certification_level: str
    mentor_id: Optional[str]
    status: str
    submitted_score_count: int
    paired_review_count: int
    agreeing_review_count: int
    irr_agreement_rate_pct: float
    demoted_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssessmentAttempt(TypedDict):
    id: str
    student_id: str
    competency_id: str
    blueprint_id: str
    term_id: str
    attempt_number: int
    status: str
    held_from_status: Optional[str]
    integrity_hold: bool
    artifact_hash: Optional[str]
    integrity_attestation_accepted: bool
    client_fingerprint: Optional[str]
    submitted_at_utc: Optional[str]
    scores_received_count: int
    final_score_pct: Optional[float]
    is_provisional_score: bool
    score_variant: Optional[str]
    critical_fail: bool
    scored_at_utc: Optional[str]
    mastered_at_utc: Optional[str]
    cooloff_until_utc: Optional[str]
    revision_count: int
    endorsement_consumed: bool
    created_at: str
    updated_at: str
    version: int


class EvaluatorScore(TypedDict):
    id: str
    attempt_id: str
    evaluator_id: str
    dimension_scores: List[Dict[str, Any]]
    narrative: Optional[str]
    weighted_score_pct: float
    critical_fail: bool
    reader_ordinal: int
    is_adjudication: bool
    submitted_at_utc: str
    status: str
    voided_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IntegrityCase(TypedDict):
    id: str
    attempt_id: str
    student_id: str
    signal_type: str
    severity: str
    note: Optional[str]
    status: str
    sanction: str
    attempt_status_at_open: str
    opened_by_user_id: str
    resolved_by_user_id: Optional[str]
    resolved_at_utc: Optional[str]
    auto_raised: bool
    created_at: str
    updated_at: str
    version: int


class AidDisbursement(TypedDict):
    id: str
    student_id: str
    term_id: str
    scheduled_amount_cents: int
    status: str
    hold_reason: Optional[str]
    credit_equivalency_at_disbursement: Optional[int]
    outstanding_amount_cents: int
    disbursed_amount_cents: int
    cancelled_amount_cents: int
    returned_amount_cents: int
    retained_amount_cents: int
    unearned_aid_cents: Optional[int]
    school_return_share_cents: Optional[int]
    student_return_share_cents: Optional[int]
    aid_review_required: bool
    disbursed_at_utc: Optional[str]
    returned_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TranscriptLine(TypedDict):
    competency_code: str
    unit_value: float
    line_credit_hours: float
    mastered_at_utc: str


class TranscriptRecord(TypedDict):
    id: str
    student_id: str
    purpose: str
    status: str
    competency_line_count: int
    total_mastered_units: float
    translated_credit_hours: float
    line_credit_hour_sum: float
    rounding_residual_credit_hours: float
    lines: List[TranscriptLine]
    issued_at_utc: Optional[str]
    voided_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# A satisfactory-academic-progress review is an append-only audit event: it
# carries only `id` and `created_at`, with no `updated_at` and no `version`.
class SapReview(TypedDict):
    id: str
    student_id: str
    term_id: str
    evaluated_at_utc: str
    terms_counted: int
    expected_units: float
    cumulative_mastered_units: float
    pace_pct: float
    pace_band: str
    previous_sap_status: str
    new_sap_status: str
    reviewed_by_user_id: str
    created_at: str


class ProgressSummary(TypedDict):
    student_id: str
    enrollment_status: str
    sap_status: str
    mastered_unit_total: float
    mastered_competency_count: int
    required_unit_total: float
    cumulative_credit_equivalency: float
    aid_credit_equivalency_sum: int
    credit_equivalency_variance: float
    aid_scheduled_total_cents: int
    aid_retained_total_cents: int
    aid_returned_total_cents: int
    active_mentor_assignment_id: Optional[str]
    cadence_status: Optional[str]
    overdue_days: int
    open_integrity_case_count: int
