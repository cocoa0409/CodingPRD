"""Entity shapes, enumerations and role names for the Alternative Education
& Credit Recovery API.

Every value here is transcribed from the product requirements document; no
value is invented.  String enums are used so that payload dictionaries can be
built with the enum member directly and still serialise as the literal the API
expects.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    """The six roles, spelled exactly as the API requires."""

    DISTRICT_ADMIN = "DistrictAdmin"
    PLACEMENT_COORDINATOR = "PlacementCoordinator"
    HOME_SCHOOL_COUNSELOR = "HomeSchoolCounselor"
    ALT_ED_TEACHER = "AltEdTeacher"
    REGISTRAR = "Registrar"
    SUPPORT_PROVIDER_STAFF = "SupportProviderStaff"


#: Roles whose ``X-User-ID`` is the identifier of a persisted entity.
SCOPE_BOUND_ROLES = (
    UserRole.PLACEMENT_COORDINATOR,
    UserRole.HOME_SCHOOL_COUNSELOR,
    UserRole.SUPPORT_PROVIDER_STAFF,
)

#: Roles whose ``X-User-ID`` is an opaque operator identifier.
OPAQUE_ROLES = (
    UserRole.DISTRICT_ADMIN,
    UserRole.REGISTRAR,
    UserRole.ALT_ED_TEACHER,
)


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class IntakePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class CohortFlag(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    PRIORITY = "PRIORITY"
    NOT_RATED = "NOT_RATED"


class SubjectArea(str, Enum):
    ELA = "ELA"
    MATH = "MATH"
    SCIENCE = "SCIENCE"
    SOCIAL_STUDIES = "SOCIAL_STUDIES"
    ELECTIVE = "ELECTIVE"


class Modality(str, Enum):
    ONLINE = "ONLINE"
    PACKET = "PACKET"
    BLENDED = "BLENDED"


class ModalityCode(str, Enum):
    ONLINE = "OL"
    PACKET = "PK"
    BLENDED = "BL"


class StudentStatus(str, Enum):
    ENROLLED_HOME = "ENROLLED_HOME"
    PLACED_ALT = "PLACED_ALT"
    RE_ENTERED = "RE_ENTERED"
    EXITED_ALT = "EXITED_ALT"
    GRADUATED = "GRADUATED"


class PriorOutcome(str, Enum):
    FAILED = "FAILED"
    PASSED = "PASSED"
    INCOMPLETE = "INCOMPLETE"


class ReplacementStatus(str, Enum):
    NOT_REPLACED = "NOT_REPLACED"
    REPLACED = "REPLACED"


class GradeReplacementPolicy(str, Enum):
    REPLACE_ON_RECOVERY = "REPLACE_ON_RECOVERY"
    AVERAGE_ON_RECOVERY = "AVERAGE_ON_RECOVERY"


class GradeReplacementMode(str, Enum):
    NONE = "NONE"
    FULL_REPLACEMENT = "FULL_REPLACEMENT"
    AVERAGED = "AVERAGED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class PlanPosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    OFF_TRACK = "OFF_TRACK"


class Pathway(str, Enum):
    BEHAVIOR = "BEHAVIOR"
    CREDIT_DEFICIENCY = "CREDIT_DEFICIENCY"
    RE_ENGAGEMENT = "RE_ENGAGEMENT"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    INFO_REQUESTED = "INFO_REQUESTED"
    PLACEMENT_OFFERED = "PLACEMENT_OFFERED"
    WAITLISTED = "WAITLISTED"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"


#: Referral statuses that count as "in flight" for the uniqueness rung.
NON_TERMINAL_REFERRAL_STATUSES = (
    ReferralStatus.SUBMITTED,
    ReferralStatus.SCREENING,
    ReferralStatus.INFO_REQUESTED,
    ReferralStatus.PLACEMENT_OFFERED,
    ReferralStatus.WAITLISTED,
)


class CreditPolicy(str, Enum):
    SEAT_TIME = "SEAT_TIME"
    COMPETENCY = "COMPETENCY"


class PlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RE_ENTRY_PENDING = "RE_ENTRY_PENDING"
    RE_ENTERED = "RE_ENTERED"
    EXITED_UNSUCCESSFUL = "EXITED_UNSUCCESSFUL"


class EnrollmentType(str, Enum):
    CREDIT_RECOVERY = "CREDIT_RECOVERY"
    NEW_CREDIT = "NEW_CREDIT"


class ProgressState(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED_FOR_AWARD = "SUBMITTED_FOR_AWARD"
    AWARDED = "AWARDED"
    AWARD_DENIED = "AWARD_DENIED"


class IntegrityState(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"
    CLEARED = "CLEARED"
    VOIDED_FOR_INTEGRITY = "VOIDED_FOR_INTEGRITY"


class PacingFlag(str, Enum):
    NOT_YET_RATED = "NOT_YET_RATED"
    ON_PACE = "ON_PACE"
    BEHIND = "BEHIND"
    CRITICAL = "CRITICAL"


class AwardStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class StationType(str, Enum):
    COMPUTER = "COMPUTER"
    PAPER = "PAPER"


class ProctorSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class ProviderRoleType(str, Enum):
    COUNSELOR = "COUNSELOR"
    SOCIAL_WORKER = "SOCIAL_WORKER"
    BEHAVIOR_SPECIALIST = "BEHAVIOR_SPECIALIST"


class ServiceCode(str, Enum):
    ACADEMIC_COUNSELING = "ACADEMIC_COUNSELING"
    BEHAVIOR_COACHING = "BEHAVIOR_COACHING"
    SOCIAL_WORK = "SOCIAL_WORK"
    RE_ENGAGEMENT_CHECKIN = "RE_ENGAGEMENT_CHECKIN"


class SupportSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class GradeCode(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"
    I = "I"


class IntegrityResolution(str, Enum):
    CLEARED = "CLEARED"
    VOIDED_FOR_INTEGRITY = "VOIDED_FOR_INTEGRITY"


# --------------------------------------------------------------------------
# Common system-managed properties
# --------------------------------------------------------------------------
class CommonFields(TypedDict):
    """The four system-managed properties every business resource carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


#: Names of the four common properties, for iteration in assertions.
COMMON_FIELD_NAMES = ("id", "created_at", "updated_at", "version")


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class HomeSchool(CommonFields, total=False):
    name: str
    district_code: str
    accountability_cohort_year: int
    cohort_size: int
    graduates_count: int
    alt_ed_placed_count: int
    adjusted_grad_rate: Optional[float]
    cohort_flag: str


class Center(CommonFields, total=False):
    name: str
    seat_capacity: int
    certified_teacher_fte: float
    support_staff_fte: float
    max_students_per_teacher: int
    restricted_seat_margin: int
    active_student_count: int
    seats_reserved: int
    seats_committed: int
    seats_available: int
    student_teacher_ratio: float
    staffing_headroom: int
    intake_posture: str


class Course(CommonFields, total=False):
    code: str
    title: str
    subject_area: str
    credit_value: float
    modality: str
    total_modules: int
    required_seat_hours: float
    pacing_days: int
    proctoring_required: bool
    proctored_exam_weight: float
    ncaa_approved: bool
    min_passing_percent: float


class Student(CommonFields, total=False):
    home_school_id: str
    state_student_id: str
    full_name: str
    cohort_year: int
    grade_level: int
    status: str
    credits_earned_total: float
    alt_ed_credits: float
    ncaa_acceptable_credits: float
    gpa: Optional[float]


class PriorCourseRecord(CommonFields, total=False):
    student_id: str
    course_id: str
    term_code: str
    original_percent: float
    credits_attempted: float
    outcome: str
    original_grade_code: str
    replacement_status: str


class GraduationPlan(CommonFields, total=False):
    student_id: str
    required_credits_total: float
    grade_replacement_policy: str
    projected_completion_term: Optional[str]
    status: str
    credits_earned: float
    credits_in_progress: float
    credits_remaining: float
    expected_credits_by_grade: float
    posture: str


class Referral(CommonFields, total=False):
    student_id: str
    center_id: str
    pathway: str
    deficiency_credits: float
    behavior_incident_count: int
    days_disengaged: int
    narrative: str
    prior_referral_id: Optional[str]
    status: str
    priority_score: float
    screening_note: Optional[str]
    missing_items: Optional[str]
    denial_reason: Optional[str]
    waitlist_reason: Optional[str]
    offer_expires_on: Optional[str]
    promoted_from_waitlist: bool


class Placement(CommonFields, total=False):
    referral_id: str
    student_id: str
    center_id: str
    credit_policy: str
    start_date: str
    status: str
    days_present: int
    days_enrolled: int
    attendance_rate: Optional[float]
    attendance_component: float
    pacing_component: float
    credit_component: float
    readiness_base_score: float
    engagement_bonus: float
    readiness_score: float
    re_entry_eligible: bool
    support_sessions_completed: int
    target_re_entry_date: Optional[str]
    actual_re_entry_date: Optional[str]
    re_entry_requested_by_user_id: Optional[str]
    re_entry_denial_reason: Optional[str]
    exit_reason: Optional[str]


class CourseEnrollment(CommonFields, total=False):
    placement_id: str
    course_id: str
    enrollment_type: str
    prior_course_record_id: Optional[str]
    enrolled_on: str
    progress_state: str
    integrity_state: str
    integrity_incident_code: Optional[str]
    integrity_resolution_note: Optional[str]
    modules_passed: int
    seat_hours_logged: float
    module_avg_percent: Optional[float]
    proctored_exam_percent: Optional[float]
    mastery_pct: Optional[float]
    final_percent: Optional[float]
    awarded_credits: Optional[float]
    projected_credits: float
    pace_index: Optional[float]
    pacing_flag: str
    submitted_by_user_id: Optional[str]
    denial_reason: Optional[str]


class CreditAward(CommonFields, total=False):
    course_enrollment_id: str
    student_id: str
    prior_course_record_id: Optional[str]
    credits_awarded: float
    award_basis: str
    posted_on: str
    modality_code: str
    transcript_code: str
    alt_ed_flag: bool
    transcript_grade_code: str
    ncaa_acceptable: bool
    grade_replacement_mode: str
    status: str
    void_reason: Optional[str]


class ProctorStation(CommonFields, total=False):
    center_id: str
    label: str
    station_type: str
    turnaround_buffer_minutes: int
    scheduled_session_count: int


class ProctorSession(CommonFields, total=False):
    course_enrollment_id: str
    proctor_station_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    score_percent: Optional[float]
    integrity_incident: Optional[bool]
    no_show_note: Optional[str]


class SupportProvider(CommonFields, total=False):
    center_id: str
    role_type: str
    full_name: str
    max_concurrent_students: int
    completed_session_count: int


class SupportSession(CommonFields, total=False):
    support_provider_id: str
    placement_id: str
    start_at: str
    end_at: str
    service_code: str
    status: str
    minutes_delivered: Optional[int]
    completion_note: Optional[str]


JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
