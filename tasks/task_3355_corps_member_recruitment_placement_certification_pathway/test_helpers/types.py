"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this API shares the same system-managed properties
(`id`, `created_at`, `updated_at`, `version`), so every TypedDict below
carries all four.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Enumerations ─────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SELECTION_MANAGER = "SelectionManager"
    APPLICANT = "Applicant"
    PLACEMENT_COORDINATOR = "PlacementCoordinator"
    INSTITUTE_DIRECTOR = "InstituteDirector"
    CERTIFICATION_OFFICER = "CertificationOfficer"
    COACH = "Coach"


class CampusTier(str, Enum):
    PRIORITY = "PRIORITY"
    STANDARD = "STANDARD"
    DEVELOPING = "DEVELOPING"


class SubjectArea(str, Enum):
    MATH = "MATH"
    SCIENCE = "SCIENCE"
    ENGLISH = "ENGLISH"
    HISTORY = "HISTORY"
    SPED = "SPED"
    BILINGUAL = "BILINGUAL"


class GradeBand(str, Enum):
    ELEMENTARY = "ELEMENTARY"
    MIDDLE = "MIDDLE"
    HIGH = "HIGH"


class CertificationTrack(str, Enum):
    STANDARD = "STANDARD"
    ALTERNATIVE_EMERGENCY = "ALTERNATIVE_EMERGENCY"
    PROVISIONAL = "PROVISIONAL"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class DistrictAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class InstituteStatus(str, Enum):
    ENROLLED = "ENROLLED"
    IN_TRAINING = "IN_TRAINING"
    COMPLETED = "COMPLETED"


class ServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    EXITED = "EXITED"


class PlacementStatus(str, Enum):
    MATCHED = "MATCHED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    EXITED_EARLY = "EXITED_EARLY"
    COMPLETED = "COMPLETED"


class MilestoneType(str, Enum):
    COURSEWORK = "COURSEWORK"
    PRACTICUM = "PRACTICUM"
    EXAM = "EXAM"
    ORIENTATION = "ORIENTATION"


class ProgressStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class DeadlineStatus(str, Enum):
    OVERDUE = "OVERDUE"
    AT_RISK = "AT_RISK"
    ON_TRACK = "ON_TRACK"
    SATISFIED = "SATISFIED"


class SupportRecordType(str, Enum):
    COACHING = "COACHING"
    EVALUATION = "EVALUATION"


class SelectionBand(str, Enum):
    STRONG = "STRONG"
    QUALIFIED = "QUALIFIED"
    DEVELOPING = "DEVELOPING"


# The canonical synthesis order of a corps member's certification milestones.
MILESTONE_TYPE_ORDER = ["COURSEWORK", "PRACTICUM", "ORIENTATION", "EXAM"]


# ─── Entity shapes ────────────────────────────────────

class Region(TypedDict):
    id: str
    region_code: str
    name: str
    state_code: str
    term_start_date: str
    base_placement_fee_cents: int
    max_corps_members: int
    created_at: str
    updated_at: str
    version: int


class PartnerDistrict(TypedDict):
    id: str
    region_id: str
    name: str
    agreement_status: str
    hiring_commitment_slots: int
    placement_fee_per_member_cents: int
    unfilled_slot_penalty_cents: int
    fee_budget_cents: int
    committed_placement_count: int
    invoice_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class PartnerSchool(TypedDict):
    id: str
    district_id: str
    name: str
    grade_band: str
    subject_needs: List[str]
    classroom_capacity: int
    occupied_classrooms: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    campus_name: str
    campus_tier: str
    graduation_year: int
    leadership_score: float
    achievement_score: float
    gpa: float
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    applicant_id: str
    preferred_region_id: str
    subject_area: str
    grade_preference: str
    status: str
    verified_gpa: Optional[float]
    revision_count: int
    selection_score: float
    final_selection_score: float
    decision_reason: Optional[str]
    reviewed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    offer_expires_at: Optional[str]
    created_corps_member_id: Optional[str]
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertificationPathway(TypedDict):
    id: str
    region_id: str
    state_code: str
    certification_track: str
    required_coursework_hours: int
    required_practice_hours: int
    deadline_days_before_term: int
    coursework_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class CorpsMember(TypedDict):
    id: str
    application_id: str
    cohort_year: int
    institute_status: str
    service_status: str
    practice_teaching_hours: int
    coursework_hours_completed: int
    certification_hours_verified: int
    readiness_score: float
    institute_stipend_cents: int
    service_started_at: Optional[str]
    leave_started_at: Optional[str]
    exit_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    corps_member_id: str
    school_id: str
    subject_area: str
    grade_band: str
    status: str
    term_start_date: str
    term_end_date: str
    confirmed_at: Optional[str]
    activated_at: Optional[str]
    early_exit_reason: Optional[str]
    employment_eligible: bool
    placement_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class CertificationMilestone(TypedDict):
    id: str
    corps_member_id: str
    pathway_id: str
    milestone_type: str
    required_hours: int
    due_date: str
    progress_status: str
    verification_status: str
    completed_at: Optional[str]
    completed_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    deadline_status: str
    days_remaining: int
    created_at: str
    updated_at: str
    version: int


class SupportRecord(TypedDict):
    id: str
    corps_member_id: str
    record_type: str
    coach_user_id: str
    session_start: str
    session_end: str
    effectiveness_score: int
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int
