"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISTRICT_ADMIN = "DistrictAdmin"
    REGISTRAR = "Registrar"
    STATE_REPORTER = "StateReporter"
    PORTAL_USER = "PortalUser"


class DistrictStatus(str, Enum):
    IMPLEMENTATION = "IMPLEMENTATION"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"


class SchoolYearStatus(str, Enum):
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    CLOSED_FOR_REPORTING = "CLOSED_FOR_REPORTING"
    ROLLED_OVER = "ROLLED_OVER"
    ARCHIVED = "ARCHIVED"


class SpecStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class StudentStatus(str, Enum):
    PRE_REGISTERED = "PRE_REGISTERED"
    ENROLLED = "ENROLLED"
    INACTIVE = "INACTIVE"
    GRADUATED = "GRADUATED"
    ARCHIVED = "ARCHIVED"


class SectionStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"


class EnrollmentLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class AbsencePosture(str, Enum):
    CLEAR = "CLEAR"
    AT_RISK = "AT_RISK"
    CHRONIC = "CHRONIC"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"


class IncidentActionType(str, Enum):
    NONE = "NONE"
    ISS = "ISS"
    OSS = "OSS"
    EXPULSION = "EXPULSION"


class ExtractStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class EscalationPriority(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    URGENT = "URGENT"


class PortalAccountStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class PortalAccountType(str, Enum):
    PARENT = "PARENT"
    STUDENT = "STUDENT"


class PortalAccessLevel(str, Enum):
    FULL = "FULL"
    GRADES_ONLY = "GRADES_ONLY"
    ATTENDANCE_ONLY = "ATTENDANCE_ONLY"


class GradeVisibility(str, Enum):
    ALL_GRADES = "ALL_GRADES"
    CURRENT_TERM_ONLY = "CURRENT_TERM_ONLY"
    HIDDEN = "HIDDEN"


class FeedPlatform(str, Enum):
    ASSESSMENT = "ASSESSMENT"
    FOOD_SERVICE = "FOOD_SERVICE"
    TRANSPORTATION = "TRANSPORTATION"
    LMS = "LMS"


class FeedStatus(str, Enum):
    PENDING = "PENDING"
    IN_SYNC = "IN_SYNC"
    FAILED = "FAILED"


class RolloverRunStatus(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    COMPENSATED = "COMPENSATED"
    SUPERSEDED = "SUPERSEDED"


class FundingMethod(str, Enum):
    ADM = "ADM"
    COUNT_DATE = "COUNT_DATE"


GRADE_LEVELS = ["KG", "01", "02", "03", "04", "05", "06", "07",
                "08", "09", "10", "11", "12"]


class District(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SchoolYear(TypedDict, total=False):
    id: str
    district_id: str
    label: str
    start_date: str
    end_date: str
    instructional_days: int
    count_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StateCollectionSpec(TypedDict, total=False):
    id: str
    state_code: str
    funding_method: str
    attendance_code_map: dict
    discipline_code_map: dict
    program_code_map: dict
    submission_window_opens_at: str
    submission_window_closes_at: str
    chronic_absence_threshold: float
    auto_withdraw_streak: int
    min_membership_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    district_id: str
    student_number: str
    first_name: str
    last_name: str
    birth_date: str
    entry_grade_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict, total=False):
    id: str
    district_id: str
    course_code: str
    title: str
    credit_hours: float
    grade_band: str
    state_course_code: str
    created_at: str
    updated_at: str
    version: int


class Section(TypedDict, total=False):
    id: str
    course_id: str
    school_year_id: str
    teacher_ref: Optional[str]
    term_label: str
    room: str
    period_start_min: int
    period_end_min: int
    capacity: int
    roster_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    student_id: str
    school_year_id: str
    grade_level: str
    program_code: Optional[str]
    state_program_code: Optional[str]
    program_weight: float
    entry_date: str
    exit_date: Optional[str]
    prior_segment_days: int
    membership_days: int
    absence_weight_sum: float
    absence_rate: float
    fte_adm: float
    fte_count_date: float
    lifecycle: str
    absence_posture: str
    created_at: str
    updated_at: str
    version: int


class AttendanceEvent(TypedDict, total=False):
    # Immutable ledger entry: id + created_at only, no updated_at / version (PRD §2.5).
    id: str
    enrollment_id: str
    attendance_date: str
    raw_code: str
    state_attendance_code: str
    absence_weight: float
    is_excused: bool
    created_at: str


class DisciplineIncident(TypedDict, total=False):
    id: str
    student_id: str
    enrollment_id: str
    incident_date: str
    raw_offense_code: str
    action_type: str
    action_days: int
    state_offense_code: str
    severity_base: int
    severity_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReportingExtract(TypedDict, total=False):
    id: str
    school_year_id: str
    collection_spec_id: str
    generation: int
    status: str
    record_count: int
    invalid_record_count: int
    total_fte_millis: int
    chronic_absentee_count: int
    escalation_priority: str
    supersedes_extract_id: Optional[str]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PortalAccount(TypedDict, total=False):
    id: str
    student_id: str
    account_type: str
    access_level: str
    grade_visibility: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IntegrationFeed(TypedDict, total=False):
    id: str
    district_id: str
    platform: str
    status: str
    last_synced_roster_count: Optional[int]
    last_synced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RolloverRun(TypedDict, total=False):
    id: str
    district_id: str
    source_school_year_id: str
    target_school_year_id: str
    status: str
    promoted_count: int
    graduated_count: int
    archived_student_count: int
    created_at: str
    updated_at: str
    version: int
