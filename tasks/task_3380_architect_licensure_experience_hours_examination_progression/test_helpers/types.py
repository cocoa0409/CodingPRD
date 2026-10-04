"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CANDIDATE = "Candidate"
    SUPERVISOR = "Supervisor"
    BOARD_ADMINISTRATOR = "BoardAdministrator"
    NCARB_ADMINISTRATOR = "NcarbAdministrator"


class EducationStatus(str, Enum):
    NONE = "NONE"
    SATISFIED = "SATISFIED"


class ExperienceStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class ExamStatus(str, Enum):
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    AUTHORIZED = "AUTHORIZED"
    ALL_PASSED = "ALL_PASSED"


class RecordStanding(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"


class PathType(str, Enum):
    ACCREDITED_DEGREE = "ACCREDITED_DEGREE"
    ALTERNATIVE_PATH = "ALTERNATIVE_PATH"


class EvaluationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SATISFIED = "SATISFIED"
    DEFICIENT = "DEFICIENT"


class ReviewDecision(str, Enum):
    SATISFIED = "SATISFIED"
    DEFICIENT = "DEFICIENT"


class PracticeArea(str, Enum):
    PRACTICE_MANAGEMENT = "PRACTICE_MANAGEMENT"
    PROJECT_MANAGEMENT = "PROJECT_MANAGEMENT"
    PROGRAMMING_ANALYSIS = "PROGRAMMING_ANALYSIS"
    PROJECT_PLANNING_DESIGN = "PROJECT_PLANNING_DESIGN"
    PROJECT_DEVELOPMENT_DOCUMENTATION = "PROJECT_DEVELOPMENT_DOCUMENTATION"
    CONSTRUCTION_EVALUATION = "CONSTRUCTION_EVALUATION"


class WorkSetting(str, Enum):
    ARCHITECTURAL_FIRM = "ARCHITECTURAL_FIRM"
    GOVERNMENT = "GOVERNMENT"
    OTHER = "OTHER"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    RETURNED = "RETURNED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DivisionCode(str, Enum):
    PCM = "PCM"
    PJM = "PJM"
    PA = "PA"
    PPD = "PPD"
    PDD = "PDD"
    CE = "CE"


class DivisionStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class ExamResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SupplementalStatus(str, Enum):
    REGISTERED = "REGISTERED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class TransmittalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    LICENSE_GRANTED = "LICENSE_GRANTED"
    LICENSE_DENIED = "LICENSE_DENIED"
    CANCELLED = "CANCELLED"


class TransmittalOutcome(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


class DisciplinaryStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_CLEAR = "RESOLVED_CLEAR"
    RESOLVED_SANCTION = "RESOLVED_SANCTION"


class ResolveOutcome(str, Enum):
    CLEAR = "CLEAR"
    SANCTION = "SANCTION"


class AuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"


class Candidate(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    home_jurisdiction_code: str
    education_status: str
    experience_status: str
    exam_status: str
    certificate_eligible: bool
    record_standing: str
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict, total=False):
    id: str
    code: str
    name: str
    requires_supplemental_exam: bool
    min_total_experience_hours: int
    ce_hours_required: int
    ce_hsw_hours_required: int
    ce_carry_over_allowed: bool
    created_at: str
    updated_at: str
    version: int


class Supervisor(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    jurisdiction_code: str
    license_status: str
    created_at: str
    updated_at: str
    version: int


class EducationEvaluation(TypedDict, total=False):
    id: str
    candidate_id: str
    path_type: str
    institution_name: str
    semester_credit_hours: int
    status: str
    deficiency_notes: Optional[str]
    review_count: int
    created_at: str
    updated_at: str
    version: int


class ExperienceReport(TypedDict, total=False):
    id: str
    candidate_id: str
    supervisor_id: str
    practice_area: str
    hours: float
    work_period_start: str
    work_period_end: str
    work_setting: str
    status: str
    submitted_at: Optional[str]
    credit_pct: int
    credited_hours: int
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExamAuthorization(TypedDict, total=False):
    id: str
    candidate_id: str
    jurisdiction_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExamDivisionProgress(TypedDict, total=False):
    id: str
    candidate_id: str
    authorization_id: str
    division_code: str
    status: str
    scheduled_date: Optional[str]
    attempt_count: int
    attempt_dates: List[str]
    last_failed_at: Optional[str]
    passed_at: Optional[str]
    expires_at: Optional[str]
    result: Optional[str]
    scaled_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SupplementalExam(TypedDict, total=False):
    id: str
    candidate_id: str
    jurisdiction_code: str
    exam_date: str
    status: str
    result: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    candidate_id: str
    serial_number: str
    home_jurisdiction_code: str
    ce_hours_required: int
    ce_hsw_hours_required: int
    status: str
    issued_at: str
    period_start: str
    period_end: str
    renewal_count: int
    ce_hours_current_period: int
    ce_hsw_current_period: int
    lifetime_ce_hours: int
    created_at: str
    updated_at: str
    version: int


class CEEntry(TypedDict, total=False):
    id: str
    certificate_id: str
    hours: int
    hsw: bool
    completed_date: str
    provider: str
    voided: bool
    created_at: str
    updated_at: str
    version: int


class Transmittal(TypedDict, total=False):
    id: str
    certificate_id: str
    jurisdiction_code: str
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisciplinaryReport(TypedDict, total=False):
    id: str
    candidate_id: str
    jurisdiction_code: str
    allegation: str
    filed_by_user_id: str
    status: str
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int
