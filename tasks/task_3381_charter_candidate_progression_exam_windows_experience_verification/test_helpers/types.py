"""Domain types: entity TypedDicts, status enums, role enum.

Every enum value and field name is PRD-exact (PRD §2.1, §3.1-§3.9). All 13
resources carry the four system-managed properties id/created_at/updated_at/
version (PRD §2.5).

API MANIFEST (frozen for Phase B):
  Enums (all `str, Enum`, members named exactly as the wire value):
    UserRole                — CANDIDATE/PROGRAM_ADMIN/PROCTOR/EXPERIENCE_REVIEWER/
                              REFERENCE_PROVIDER/CONDUCT_INVESTIGATOR/CONDUCT_ADJUDICATOR
    Pathway                 — EDUCATION | WORK_EXPERIENCE
    EnrollmentStatus        — PENDING_PAYMENT | ENROLLED | CHARTER_AWARDED
    LevelCode               — LEVEL_I | LEVEL_II | LEVEL_III
    CycleStatus             — PUBLISHED | ARCHIVED
    WindowStatus            — OPEN | RESULTS_PUBLISHED | CANCELLED
    CalculatorModel         — TI_BA_II_PLUS | HP_12C
    FeeTier                 — EARLY | STANDARD
    BookingStatus           — SCHEDULED | CHECKED_IN | COMPLETED | CANCELLED | NO_SHOW
    ComplianceStatus        — CLEAR | POLICY_FLAGGED | CONFIRMED_VIOLATION | CLEARED
    AttemptResult           — PASS | FAIL
    ScoreStatus             — AWAITING_SCORE | SCORED
    AttemptValidity         — VALID | INVALIDATED | REINSTATED
    SubmissionStatus        — DRAFT | SUBMITTED | APPROVED | REJECTED | RETURNED_FOR_REVISION
    ReviewDecision          — APPROVED | REJECTED | RETURNED_FOR_REVISION
    ReferenceStatus         — PENDING | VERIFIED | DECLINED | EXPIRED
    ReferenceDecision       — VERIFIED | DECLINED
    CaseOrigin              — EXAM_INCIDENT | CONDUCT_STATEMENT | EXTERNAL_REPORT
    CaseStatus              — OPENED | SANCTIONED | DISMISSED | APPEALED
    SanctionType            — WARNING | SUSPENSION_12M | EXAM_INVALIDATION | CHARTER_REVOCATION
    CaseOutcome             — SANCTIONED | DISMISSED
    MembershipStatus        — ACTIVE | TERMINATED
    ConductStanding         — GOOD_STANDING | SUSPENDED | REVOKED
  TypedDicts (response shapes; Optional[...] marks nullable-at-rest fields):
    Candidate, ProgramEnrollment, ExamLevel, CurriculumCycle, ExamWindow,
    TestCenter, ExamAppointment, ExamAttempt, WorkExperienceSubmission,
    ReferenceContact, MisconductCase, Society, SocietyMembership
  Helper TypedDicts (embedded sub-structures):
    ConductStatementEntry, BlackoutWindow, ExperienceSegment, CeRecord
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1 — exactly seven roles, spelled as below)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CANDIDATE = "Candidate"
    PROGRAM_ADMIN = "ProgramAdmin"
    PROCTOR = "Proctor"
    EXPERIENCE_REVIEWER = "ExperienceReviewer"
    REFERENCE_PROVIDER = "ReferenceProvider"
    CONDUCT_INVESTIGATOR = "ConductInvestigator"
    CONDUCT_ADJUDICATOR = "ConductAdjudicator"


# ---------------------------------------------------------------------------
# Status / vocabulary enums
# ---------------------------------------------------------------------------
class Pathway(str, Enum):
    EDUCATION = "EDUCATION"
    WORK_EXPERIENCE = "WORK_EXPERIENCE"


class EnrollmentStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ENROLLED = "ENROLLED"
    CHARTER_AWARDED = "CHARTER_AWARDED"


class LevelCode(str, Enum):
    LEVEL_I = "LEVEL_I"
    LEVEL_II = "LEVEL_II"
    LEVEL_III = "LEVEL_III"


class CycleStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    RESULTS_PUBLISHED = "RESULTS_PUBLISHED"
    CANCELLED = "CANCELLED"


class CalculatorModel(str, Enum):
    TI_BA_II_PLUS = "TI_BA_II_PLUS"
    HP_12C = "HP_12C"


class FeeTier(str, Enum):
    EARLY = "EARLY"
    STANDARD = "STANDARD"


class BookingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ComplianceStatus(str, Enum):
    CLEAR = "CLEAR"
    POLICY_FLAGGED = "POLICY_FLAGGED"
    CONFIRMED_VIOLATION = "CONFIRMED_VIOLATION"
    CLEARED = "CLEARED"


class AttemptResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ScoreStatus(str, Enum):
    AWAITING_SCORE = "AWAITING_SCORE"
    SCORED = "SCORED"


class AttemptValidity(str, Enum):
    VALID = "VALID"
    INVALIDATED = "INVALIDATED"
    REINSTATED = "REINSTATED"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"


class ReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"


class ReferenceStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class ReferenceDecision(str, Enum):
    VERIFIED = "VERIFIED"
    DECLINED = "DECLINED"


class CaseOrigin(str, Enum):
    EXAM_INCIDENT = "EXAM_INCIDENT"
    CONDUCT_STATEMENT = "CONDUCT_STATEMENT"
    EXTERNAL_REPORT = "EXTERNAL_REPORT"


class CaseStatus(str, Enum):
    OPENED = "OPENED"
    SANCTIONED = "SANCTIONED"
    DISMISSED = "DISMISSED"
    APPEALED = "APPEALED"


class SanctionType(str, Enum):
    WARNING = "WARNING"
    SUSPENSION_12M = "SUSPENSION_12M"
    EXAM_INVALIDATION = "EXAM_INVALIDATION"
    CHARTER_REVOCATION = "CHARTER_REVOCATION"


class CaseOutcome(str, Enum):
    SANCTIONED = "SANCTIONED"
    DISMISSED = "DISMISSED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ConductStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Embedded sub-structures
# ---------------------------------------------------------------------------
class ConductStatementEntry(TypedDict, total=False):
    disclosure_year: int
    has_disclosures: bool
    disclosure_text: Optional[str]
    created_at: str


class BlackoutWindow(TypedDict):
    blackout_start_date: str  # ISO YYYY-MM-DD, inclusive
    blackout_end_date: str    # ISO YYYY-MM-DD, inclusive
    reason: str


class ExperienceSegment(TypedDict):
    employer_name: str
    role_title: str
    start_date: str           # ISO YYYY-MM-DD
    end_date: str             # ISO YYYY-MM-DD, >= start_date
    qualifying_activity_pct: float  # 0..100
    hours: float              # > 0


class CeRecord(TypedDict):
    activity_title: str
    credit_hours: float       # one decimal place
    completed_on: str         # ISO YYYY-MM-DD


# ---------------------------------------------------------------------------
# Entity TypedDicts (response shapes). All carry id/created_at/updated_at/
# version per PRD §2.5.
# ---------------------------------------------------------------------------
class Candidate(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    date_of_birth: str
    gov_id_number: str
    highest_level_passed_code: Optional[str]
    charter_awarded: bool
    suspended_until: Optional[str]
    conduct_revoked: bool
    conduct_standing: str
    conduct_statements: List[ConductStatementEntry]
    created_at: str
    updated_at: str
    version: int


class ProgramEnrollment(TypedDict, total=False):
    id: str
    candidate_id: str
    pathway: str
    degree_completed: Optional[bool]
    graduation_date: Optional[str]
    declared_work_months: Optional[int]
    declared_work_hours: Optional[int]
    scholarship_pct: float
    status: str
    lifetime_charges_cents: int
    lifetime_payments_cents: int
    lifetime_credits_posted_cents: int
    lifetime_credits_applied_cents: int
    credit_balance_cents: int
    outstanding_balance_cents: int
    net_billed_cents: int
    curriculum_access_cycle_ids: List[str]
    chartered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExamLevel(TypedDict, total=False):
    id: str
    level_code: str
    mps_scaled_score: int
    max_attempts: int
    early_fee_cents: int
    standard_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class CurriculumCycle(TypedDict, total=False):
    id: str
    exam_level_id: str
    cycle_year: int
    effective_from: str
    effective_to: str
    content_version: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExamWindow(TypedDict, total=False):
    id: str
    exam_level_id: str
    window_opens_at: str
    window_closes_at: str
    scheduling_deadline_at: str
    reschedule_deadline_at: str
    early_fee_deadline_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TestCenter(TypedDict, total=False):
    id: str
    name: str
    city: str
    daily_seat_capacity: int
    blackout_windows: List[BlackoutWindow]
    created_at: str
    updated_at: str
    version: int


class ExamAppointment(TypedDict, total=False):
    id: str
    program_enrollment_id: str
    exam_window_id: str
    test_center_id: str
    candidate_id: str
    exam_date: str
    calculator_model: str
    fee_tier: str
    exam_fee_cents: int
    reschedule_count: int
    reschedule_fees_total_cents: int
    booking_status: str
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class ExamAttempt(TypedDict, total=False):
    id: str
    exam_appointment_id: str
    candidate_id: str
    exam_level_code: str
    attempt_sequence: int
    scaled_score: Optional[int]
    result: Optional[str]
    score_status: str
    validity: str
    created_at: str
    updated_at: str
    version: int


class WorkExperienceSubmission(TypedDict, total=False):
    id: str
    candidate_id: str
    segments: List[ExperienceSegment]
    provisional_months: Optional[int]
    committee_months: Optional[int]
    status: str
    reviewer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReferenceContact(TypedDict, total=False):
    id: str
    experience_submission_id: str
    referee_name: str
    referee_email: str
    status: str
    expires_at: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MisconductCase(TypedDict, total=False):
    id: str
    candidate_id: str
    appointment_id: Optional[str]
    origin: str
    allegation: str
    investigator_user_id: Optional[str]
    adjudicator_user_id: Optional[str]
    status: str
    sanction_type: Optional[str]
    sanctioned_at: Optional[str]
    appeal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Society(TypedDict, total=False):
    id: str
    society_code: str
    name: str
    region: str
    annual_dues_cents: int
    ce_credits_required_per_year: int
    created_at: str
    updated_at: str
    version: int


class SocietyMembership(TypedDict, total=False):
    id: str
    candidate_id: str
    society_id: str
    status: str
    paid_through_year: int
    ce_records: List[CeRecord]
    calendar_year_credits: float
    rolling_12m_credits: float
    ce_standing_met: bool
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "Pathway",
    "EnrollmentStatus",
    "LevelCode",
    "CycleStatus",
    "WindowStatus",
    "CalculatorModel",
    "FeeTier",
    "BookingStatus",
    "ComplianceStatus",
    "AttemptResult",
    "ScoreStatus",
    "AttemptValidity",
    "SubmissionStatus",
    "ReviewDecision",
    "ReferenceStatus",
    "ReferenceDecision",
    "CaseOrigin",
    "CaseStatus",
    "SanctionType",
    "CaseOutcome",
    "MembershipStatus",
    "ConductStanding",
    "ConductStatementEntry",
    "BlackoutWindow",
    "ExperienceSegment",
    "CeRecord",
    "Candidate",
    "ProgramEnrollment",
    "ExamLevel",
    "CurriculumCycle",
    "ExamWindow",
    "TestCenter",
    "ExamAppointment",
    "ExamAttempt",
    "WorkExperienceSubmission",
    "ReferenceContact",
    "MisconductCase",
    "Society",
    "SocietyMembership",
]
