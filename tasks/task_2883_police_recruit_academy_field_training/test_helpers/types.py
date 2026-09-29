"""Domain types for the Police Recruit Academy & Field Training API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  The TrainingRecordEntry is the single append-only resource:
it carries only ``id`` and ``created_at`` and therefore has neither
``updated_at`` nor ``version``.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    ACADEMY_DIRECTOR = "AcademyDirector"
    TRAINING_COORDINATOR = "TrainingCoordinator"
    BACKGROUND_INVESTIGATOR = "BackgroundInvestigator"
    MEDICAL_EXAMINER = "MedicalExaminer"
    ACADEMY_INSTRUCTOR = "AcademyInstructor"
    FIELD_TRAINING_OFFICER = "FieldTrainingOfficer"
    RECORDS_CUSTODIAN = "RecordsCustodian"
    RECRUIT = "Recruit"


ALL_ROLES = [r.value for r in UserRole]


class AcademyClassStatus(str, Enum):
    FORMING = "FORMING"
    IN_SESSION = "IN_SESSION"
    AT_RISK = "AT_RISK"
    GRADUATED = "GRADUATED"


class PipelineStage(str, Enum):
    APPLICANT = "APPLICANT"
    SCREENING = "SCREENING"
    ACADEMY = "ACADEMY"
    FIELD_TRAINING = "FIELD_TRAINING"
    PROBATION = "PROBATION"
    CERTIFIED = "CERTIFIED"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class ClearanceStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    CLEARED = "CLEARED"
    DISQUALIFIED = "DISQUALIFIED"


class AcademyStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    REMEDIATION = "REMEDIATION"
    DISMISSAL_PENDING = "DISMISSAL_PENDING"
    COMPLETE = "COMPLETE"


class ProbationStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ACTIVE = "ACTIVE"
    EXTENSION_REQUIRED = "EXTENSION_REQUIRED"
    PASSED = "PASSED"
    SEPARATED = "SEPARATED"


class DismissalReasonCode(str, Enum):
    ACADEMIC_FAILURE = "ACADEMIC_FAILURE"
    ABSENCE_LIMIT = "ABSENCE_LIMIT"
    INTEGRITY = "INTEGRITY"
    MEDICAL = "MEDICAL"
    FIELD_TRAINING_FAILURE = "FIELD_TRAINING_FAILURE"
    PROBATION_SEPARATION = "PROBATION_SEPARATION"
    VOLUNTARY_WITHDRAWAL = "VOLUNTARY_WITHDRAWAL"


class ScreeningType(str, Enum):
    BACKGROUND = "BACKGROUND"
    MEDICAL = "MEDICAL"
    PSYCHOLOGICAL = "PSYCHOLOGICAL"
    PHYSICAL_FITNESS = "PHYSICAL_FITNESS"


ALL_SCREENING_TYPES = [s.value for s in ScreeningType]


class ScreeningRecordStatus(str, Enum):
    ORDERED = "ORDERED"
    FINDINGS_RECORDED = "FINDINGS_RECORDED"
    RETEST_REQUIRED = "RETEST_REQUIRED"
    CLEARED = "CLEARED"
    WAIVED = "WAIVED"
    DISQUALIFIED = "DISQUALIFIED"


class ScreeningDecision(str, Enum):
    CLEAR = "CLEAR"
    WAIVE = "WAIVE"
    DISQUALIFY = "DISQUALIFY"
    RETEST = "RETEST"


class AgeBracket(str, Enum):
    AGE_20_29 = "AGE_20_29"
    AGE_30_39 = "AGE_30_39"
    AGE_40_49 = "AGE_40_49"


class InstructorCertificationStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LessonPlanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class CourseSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    UNDER_MIN_ENROLLMENT = "UNDER_MIN_ENROLLMENT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    PARTIAL = "PARTIAL"
    ABSENT_EXCUSED = "ABSENT_EXCUSED"
    ABSENT_UNEXCUSED = "ABSENT_UNEXCUSED"


class LedgerStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CREDITED = "CREDITED"
    VOIDED = "VOIDED"


class ExaminationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    REMEDIATION_ASSIGNED = "REMEDIATION_ASSIGNED"
    FAILED_FINAL = "FAILED_FINAL"


class RotationStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    REMEDIAL = "REMEDIAL"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class TrainingRecordKind(str, Enum):
    STAGE_ENTRY = "STAGE_ENTRY"
    ADVERSE_EXIT = "ADVERSE_EXIT"
    HOURS_CREDIT = "HOURS_CREDIT"
    HOURS_REVERSAL = "HOURS_REVERSAL"
    SCREENING_ADJUDICATION = "SCREENING_ADJUDICATION"
    EXAM_RESULT = "EXAM_RESULT"
    DOR_FILED = "DOR_FILED"
    PROBATION_DECISION = "PROBATION_DECISION"
    CERTIFICATION_ISSUED = "CERTIFICATION_ISSUED"


class ProbationDecision(str, Enum):
    PASS = "PASS"
    EXTEND = "EXTEND"
    SEPARATE = "SEPARATE"


DOR_DIMENSIONS = [
    "officer_safety",
    "driving",
    "report_writing",
    "decision_making",
    "demeanor",
]


class CertificationStandard(TypedDict):
    id: str
    code: str
    state_code: str
    min_total_hours: float
    min_passing_score: float
    max_remediation_attempts: int
    max_absence_hours: float
    topic_requirements: List[Dict[str, Any]]
    fitness_event_floor_points: int
    fitness_pass_score: int
    created_at: str
    updated_at: str
    version: int


class AcademyClass(TypedDict):
    id: str
    certification_standard_id: str
    class_code: str
    start_date: str
    planned_seats: int
    status: str
    credited_topic_hours_total: float
    unmet_topic_hours: Dict[str, float]
    projected_topic_hours: Dict[str, float]
    graduated_count: int
    created_at: str
    updated_at: str
    version: int


class Recruit(TypedDict):
    id: str
    academy_class_id: str
    applicant_number: str
    full_name: str
    date_of_birth: str
    age_bracket: str
    pipeline_stage: str
    clearance_status: str
    academy_status: str
    probation_status: str
    credited_hours_total: float
    scheduled_basis_hours_total: float
    per_topic_credited_hours: Dict[str, float]
    unexcused_absence_hours: float
    make_up_hours_owed: float
    remediation_attempts_used: int
    probation_start: Optional[str]
    probation_base_days: Optional[int]
    probation_extension_days: int
    probation_milestone_due_date: Optional[str]
    probation_milestone_score: Optional[float]
    probation_scheduled_end: Optional[str]
    dismissal_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScreeningRecord(TypedDict):
    id: str
    recruit_id: str
    screening_type: str
    status: str
    attempt_number: int
    raw_metrics: Optional[Dict[str, Any]]
    composite_score: Optional[float]
    disqualifier_codes: List[str]
    waiver_justification: Optional[str]
    findings_recorded_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    findings_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    badge_number: str
    full_name: str
    certification_status: str
    certification_expires_at: Optional[str]
    authorized_topic_codes: List[str]
    fto_certified: bool
    active_trainee_count: int
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LessonPlan(TypedDict):
    id: str
    instructor_id: str
    topic_code: str
    title: str
    contact_hours: float
    status: str
    revision_number: int
    approved_revision_number: Optional[int]
    approved_at: Optional[str]
    approved_by_user_id: Optional[str]
    reviewer_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourseSession(TypedDict):
    id: str
    academy_class_id: str
    lesson_plan_id: str
    instructor_id: str
    room_code: str
    starts_at: str
    ends_at: str
    min_enrollment: int
    scheduled_hours: float
    topic_code: str
    pinned_lesson_plan_revision: Optional[int]
    status: str
    enrolled_count: int
    credited_hours_total: float
    void_reason: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict):
    id: str
    course_session_id: str
    recruit_id: str
    status: str
    present_hours: float
    ledger_status: str
    credited_hours: float
    counted_absence_hours: float
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Examination(TypedDict):
    id: str
    recruit_id: str
    topic_code: str
    attempt_number: int
    raw_score: Optional[float]
    passing_score: float
    status: str
    remediation_hours: float
    graded_at: Optional[str]
    graded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldTrainingRotation(TypedDict):
    id: str
    recruit_id: str
    fto_instructor_id: str
    prior_rotation_id: Optional[str]
    phase_number: int
    start_date: str
    end_date: str
    status: str
    dor_count: int
    remedial_flag_count: int
    competency_score: Optional[float]
    rolling_mean_score: Optional[float]
    final_narrative: Optional[str]
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ObservationReport(TypedDict):
    id: str
    field_training_rotation_id: str
    author_instructor_id: str
    observed_on: str
    dimension_ratings: Dict[str, int]
    not_responding_to_training: bool
    narrative: str
    dor_mean: float
    voided: bool
    created_at: str
    updated_at: str
    version: int


class TrainingRecordEntry(TypedDict):
    """Append-only and immutable: carries only ``id`` and ``created_at``."""
    id: str
    recruit_id: str
    academy_class_id: str
    kind: str
    stage_code: Optional[str]
    hours_delta: float
    topic_code: Optional[str]
    actor_role: str
    actor_user_id: str
    subject_entity: str
    subject_entity_id: str
    detail: str
    recorded_at_utc: str
    created_at: str
