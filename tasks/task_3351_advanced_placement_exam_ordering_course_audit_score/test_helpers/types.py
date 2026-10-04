"""Domain types for the Advanced Placement Exam Program API.

Every persisted entity in this surface carries the full common property set
(id, created_at, updated_at, version), so every TypedDict below declares all
four alongside the entity's own fields.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SCHOOL_COORDINATOR = "SchoolCoordinator"
    COURSE_AUDIT_REVIEWER = "CourseAuditReviewer"
    ACCOMMODATION_REVIEWER = "AccommodationReviewer"
    SCORING_SPECIALIST = "ScoringSpecialist"
    INTEGRITY_INVESTIGATOR = "IntegrityInvestigator"
    READER = "Reader"
    SCHOOL_STUDENT = "SchoolStudent"


class SchoolTestCenterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class CourseAuditStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderingWindow(str, Enum):
    NOT_OPEN = "NOT_OPEN"
    REGULAR = "REGULAR"
    LATE = "LATE"
    CLOSED = "CLOSED"


class ExamOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    MATERIALS_SHIPPED = "MATERIALS_SHIPPED"
    MATERIALS_RECEIVED = "MATERIALS_RECEIVED"
    DELIVERED = "DELIVERED"
    VOIDED = "VOIDED"


class RegistrationTier(str, Enum):
    REGULAR = "REGULAR"
    LATE = "LATE"
    EMERGENCY = "EMERGENCY"


class ExamRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    FEE_PENDING = "FEE_PENDING"
    CONFIRMED = "CONFIRMED"
    MATERIAL_ASSIGNED = "MATERIAL_ASSIGNED"
    SCORED = "SCORED"
    SCORE_RELEASED = "SCORE_RELEASED"
    CANCELLED = "CANCELLED"
    INVALIDATED = "INVALIDATED"


class AccommodationType(str, Enum):
    EXTENDED_TIME = "EXTENDED_TIME"
    ALTERNATE_FORMAT = "ALTERNATE_FORMAT"
    SMALL_GROUP = "SMALL_GROUP"
    BREAK_AS_NEEDED = "BREAK_AS_NEEDED"


class AccommodationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_DOC_REVIEW = "UNDER_DOC_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class AlternateReasonCode(str, Enum):
    SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT"
    ILLNESS = "ILLNESS"
    RELIGIOUS_OBSERVANCE = "RELIGIOUS_OBSERVANCE"
    EMERGENCY = "EMERGENCY"
    OTHER = "OTHER"


class AlternateRequestStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ExamScoreStatus(str, Enum):
    NOT_SCORED = "NOT_SCORED"
    RUBRIC_PENDING = "RUBRIC_PENDING"
    AGGREGATED = "AGGREGATED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"
    WITHHELD = "WITHHELD"
    INVALIDATED = "INVALIDATED"


class ReaderCalibrationStatus(str, Enum):
    RECRUITED = "RECRUITED"
    CALIBRATING = "CALIBRATING"
    CALIBRATED = "CALIBRATED"
    DEMOTED = "DEMOTED"
    INACTIVE = "INACTIVE"


class ReaderLoadStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    AT_CAPACITY = "AT_CAPACITY"
    DEMOTED = "DEMOTED"
    INACTIVE = "INACTIVE"


class ShipmentStatus(str, Enum):
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    SEAL_BROKEN = "SEAL_BROKEN"
    RETURNED = "RETURNED"


class RecipientType(str, Enum):
    COLLEGE = "COLLEGE"
    STUDENT = "STUDENT"
    SCHOOL = "SCHOOL"


class ScoreSendStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class IrregularityType(str, Enum):
    UNAUTHORIZED_DEVICE = "UNAUTHORIZED_DEVICE"
    IMPROPER_ADMINISTRATION = "IMPROPER_ADMINISTRATION"
    IDENTITY_DISCREPANCY = "IDENTITY_DISCREPANCY"
    MATERIAL_COMPROMISE = "MATERIAL_COMPROMISE"
    ADMINISTRATOR_MISCONDUCT = "ADMINISTRATOR_MISCONDUCT"


class IrregularityCaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    DECISION_PENDING = "DECISION_PENDING"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    APPEALED = "APPEALED"


class School(TypedDict, total=False):
    id: str
    name: str
    school_code: str
    country_code: str
    program_label_authorized: bool
    center_code: str
    seat_capacity: int
    seal_required: bool
    test_center_status: str
    accrued_fee_cents: int
    designation_slots_used: int
    created_at: str
    updated_at: str
    version: int


class CourseAudit(TypedDict, total=False):
    id: str
    school_id: str
    course_title: str
    syllabus_hash: str
    status: str
    review_round: int
    syllabus_revision_count: int
    approval_term_end_utc: Optional[str]
    decision_notes: Optional[str]
    designated_course_count: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    full_name: str
    school_id: str
    student_code: str
    grade_level: int
    accommodation_eligible: bool
    enrolled: bool
    created_at: str
    updated_at: str
    version: int


class ExamOrder(TypedDict, total=False):
    id: str
    school_id: str
    course_audit_id: str
    administration_year: int
    ordering_window: str
    status: str
    registration_count: int
    order_fee_cents: int
    provisional_order_fee_cents: int
    unused_exam_charge_cents: int
    materials_sealed: bool
    created_at: str
    updated_at: str
    version: int


class ExamRegistration(TypedDict, total=False):
    id: str
    exam_order_id: str
    student_id: str
    exam_subject: str
    registration_tier: str
    status: str
    late_fee_cents: int
    refundable_cents: int
    fees_paid_cents: int
    fee_waived: bool
    accommodation_flag: bool
    created_at: str
    updated_at: str
    version: int


class AccommodationRequest(TypedDict, total=False):
    id: str
    student_id: str
    exam_subject: str
    accommodation_type: str
    documentation_completeness: int
    extended_time_multiplier: float
    status: str
    review_round: int
    created_at: str
    updated_at: str
    version: int


class AlternateExamRequest(TypedDict, total=False):
    id: str
    exam_registration_id: str
    alternate_date_utc: str
    reason_code: str
    form_code: str
    status: str
    seat_block_conflict: bool
    created_at: str
    updated_at: str
    version: int


class ExamScore(TypedDict, total=False):
    id: str
    exam_registration_id: str
    raw_composite: float
    reader_id: Optional[str]
    ap_score: int
    reader_reliability_index: float
    status: str
    release_blocked: bool
    created_at: str
    updated_at: str
    version: int


class Reader(TypedDict, total=False):
    id: str
    full_name: str
    subject_expertise: str
    calibration_status: str
    reliability_index: float
    calibration_round_count: int
    calibration_sample_count: int
    calibration_agreement_rate: float
    calibration_index: float
    assigned_score_count: int
    load_status: str
    created_at: str
    updated_at: str
    version: int


class ExamMaterialShipment(TypedDict, total=False):
    id: str
    school_id: str
    exam_order_id: str
    carrier_tracking_id: str
    seal_number: str
    seal_verified: bool
    status: str
    storage_checkpoint_count: int
    custody_event_types: List[dict]
    custody_sequence_count: int
    created_at: str
    updated_at: str
    version: int


class ScoreSend(TypedDict, total=False):
    id: str
    exam_score_id: str
    recipient_type: str
    recipient_code: str
    designation_year: int
    fee_cents: int
    status: str
    credit_back_cents: int
    created_at: str
    updated_at: str
    version: int


class IrregularityCase(TypedDict, total=False):
    id: str
    exam_registration_id: str
    test_center_id: str
    irregularity_type: str
    status: str
    finding_code: Optional[str]
    investigation_round: int
    created_at: str
    updated_at: str
    version: int
