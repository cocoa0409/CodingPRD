"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD entity narratives. Every primary resource carries
id / created_at / updated_at / version; RankingEntry is the single exception
(it carries only id and created_at — it is never mutated in place).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums (values are the exact wire strings)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PROGRAM_ADMIN = "ProgramAdmin"
    STUDENT = "Student"
    COUNSELOR = "Counselor"
    PARTNER_STAFF = "PartnerStaff"
    COLLEGE_OFFICER = "CollegeOfficer"


class CyclePhase(str, Enum):
    SETUP = "SETUP"
    RECRUITMENT = "RECRUITMENT"
    APPLICATION_OPEN = "APPLICATION_OPEN"
    REVIEW = "REVIEW"
    RANKING = "RANKING"
    MATCH_RUN = "MATCH_RUN"
    REGULAR_DECISION = "REGULAR_DECISION"
    OUTCOME_TRACKING = "OUTCOME_TRACKING"
    CLOSED = "CLOSED"


# Fixed pipeline order of the nine cycle phases.
CYCLE_PHASE_ORDER: List[str] = [p.value for p in CyclePhase]


class AidPolicy(str, Enum):
    NO_LOAN = "NO_LOAN"
    MINIMAL_LOAN = "MINIMAL_LOAN"


class CollegeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class StudentSource(str, Enum):
    SELF = "SELF"
    COUNSELOR = "COUNSELOR"
    COMMUNITY_PARTNER = "COMMUNITY_PARTNER"
    PREP_PROGRAM = "PREP_PROGRAM"


class StudentStage(str, Enum):
    PROSPECT = "PROSPECT"
    APPLICANT = "APPLICANT"
    FINALIST = "FINALIST"
    MATCHED = "MATCHED"
    ENROLLED = "ENROLLED"


class ReferralStatus(str, Enum):
    NOMINATED = "NOMINATED"
    CONVERTED = "CONVERTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PrepProgramType(str, Enum):
    SUMMER = "SUMMER"
    SCHOLAR = "SCHOLAR"


class PrepProgramStatus(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    FINALIST = "FINALIST"
    NOT_FINALIST = "NOT_FINALIST"
    RANKING_SUBMITTED = "RANKING_SUBMITTED"
    RANKING_LOCKED = "RANKING_LOCKED"
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"
    REGULAR_POOL = "REGULAR_POOL"
    ADMITTED_REGULAR = "ADMITTED_REGULAR"
    REGULAR_DENIED = "REGULAR_DENIED"
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"


class NeedTier(str, Enum):
    HIGH = "HIGH"
    STANDARD = "STANDARD"


class VerificationFlag(str, Enum):
    NONE = "NONE"
    VERIFIED = "VERIFIED"
    DISCREPANCY = "DISCREPANCY"
    WAIVED = "WAIVED"


class MatchStatus(str, Enum):
    BINDING = "BINDING"
    ENROLLED = "ENROLLED"
    RELEASED = "RELEASED"


class AidVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    VERIFIED = "VERIFIED"


class AidPackageStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    REVISED = "REVISED"
    VOID = "VOID"


class VerificationOutcome(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    DISCREPANCY = "DISCREPANCY"
    WAIVED = "WAIVED"


class OutcomeStatus(str, Enum):
    ENROLLED_Y1 = "ENROLLED_Y1"
    PERSISTED_Y2 = "PERSISTED_Y2"
    PERSISTED_Y3 = "PERSISTED_Y3"
    GRADUATED = "GRADUATED"
    STOPPED_OUT = "STOPPED_OUT"
    NOT_PERSISTED = "NOT_PERSISTED"


class ReviewDecision(str, Enum):
    FINALIST = "FINALIST"
    NOT_FINALIST = "NOT_FINALIST"


class RegularDecision(str, Enum):
    ADMIT = "ADMIT"
    DENY = "DENY"


class VerificationDecision(str, Enum):
    VERIFY = "VERIFY"
    WAIVE = "WAIVE"


class PrepCloseOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true → id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

class MatchCycle(TypedDict):
    id: str
    name: str
    app_opens_at: str
    app_closes_at: str
    ranking_opens_at: str
    ranking_closes_at: str
    phase: str
    match_run_completed: bool
    created_at: str
    updated_at: str
    version: int


class PartnerCollege(TypedDict):
    id: str
    name: str
    aid_policy: str
    min_academic_index: int
    match_slots: int
    coa_cents: int
    status: str
    slots_committed: int
    enrolled_count: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    source: str
    student_stage: str
    created_at: str
    updated_at: str
    version: int


class Counselor(TypedDict):
    id: str
    full_name: str
    school_name: str
    state_code: str
    created_at: str
    updated_at: str
    version: int


class CommunityPartner(TypedDict):
    id: str
    org_name: str
    state_code: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    student_id: str
    cycle_id: str
    counselor_id: Optional[str]
    partner_id: Optional[str]
    note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PrepProgram(TypedDict):
    id: str
    student_id: str
    program_type: str
    cohort_label: str
    starts_on: str
    ends_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    student_id: str
    cycle_id: str
    referral_id: Optional[str]
    household_income_cents: int
    household_size: int
    self_reported_assets_cents: int
    gpa_scaled: int
    test_score: Optional[int]
    essay_text: str
    status: str
    academic_index: Optional[int]
    prep_alum: Optional[bool]
    need_tier: Optional[str]
    verification_flag: str
    matched_college_id: Optional[str]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RankingEntry(TypedDict):
    """Append-only ranking row: carries ONLY id and created_at as common
    fields — no updated_at, no version (revision replaces the whole list)."""
    id: str
    application_id: str
    college_id: str
    rank_position: int
    list_seq: int
    created_at: str


class Match(TypedDict):
    id: str
    application_id: str
    college_id: str
    cycle_id: str
    rank_position_awarded: int
    status: str
    matched_at: str
    created_at: str
    updated_at: str
    version: int


class AidPackage(TypedDict):
    id: str
    match_id: Optional[str]
    application_id: str
    college_id: str
    coa_cents: int
    efc_cents: int
    need_cents: int
    work_study_cents: int
    loan_cents: int
    grant_cents: int
    aid_variant: str
    guaranteed_full_need: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class IncomeVerification(TypedDict):
    id: str
    application_id: str
    submitted_by_counselor_id: Optional[str]
    submitted_by_partner_id: Optional[str]
    verified_income_cents: int
    verified_assets_cents: int
    verified_household_size: int
    outcome: str
    decided_by_partner_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutcomeRecord(TypedDict):
    id: str
    application_id: str
    college_id: str
    cycle_id: str
    match_id: Optional[str]
    status: str
    credits_completed: int
    last_checkpoint_at: str
    created_at: str
    updated_at: str
    version: int


class OutcomeSummary(TypedDict):
    enrolled_count: int
    on_track_numerator: int
    on_track_denominator: int
    on_track_rate_bp: int
    cohort150_numerator: int
    cohort150_denominator: int
    cohort150_rate_bp: int


class RunMatchResult(TypedDict):
    matched_count: int
    unmatched_count: int
