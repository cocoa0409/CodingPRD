"""Domain types: entity TypedDicts, status enums, role enum (PRD §2 and §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    AUDITOR = "Auditor"
    CENTER_MANAGER = "CenterManager"
    PROCTOR = "Proctor"
    EXAMINEE = "Examinee"
    SCORE_ANALYST = "ScoreAnalyst"


class AuthorizationStatus(str, Enum):
    APPLIED = "APPLIED"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"


class AuditOutcome(str, Enum):
    NONE = "NONE"
    PASSED = "PASSED"
    FAILED = "FAILED"


class AuditType(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    UNANNOUNCED = "UNANNOUNCED"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class AuditRecordOutcome(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class StaffRole(str, Enum):
    PROCTOR = "PROCTOR"
    CENTER_MANAGER = "CENTER_MANAGER"


class CertificationLevel(str, Enum):
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"


class SessionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    ADMINISTERED = "ADMINISTERED"
    SCORED = "SCORED"
    CANCELLED = "CANCELLED"


class IdDocumentType(str, Enum):
    PASSPORT = "PASSPORT"
    NATIONAL_ID = "NATIONAL_ID"
    DRIVERS_LICENSE = "DRIVERS_LICENSE"


class ExamineeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BANNED = "BANNED"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"


class AttendanceStatus(str, Enum):
    PENDING = "PENDING"
    ADMITTED = "ADMITTED"
    DENIED = "DENIED"
    NO_SHOW = "NO_SHOW"
    COMPLETED = "COMPLETED"


class Pool(str, Enum):
    GENERAL = "GENERAL"
    ACCOMMODATION = "ACCOMMODATION"


class DocumentCheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class BiometricResult(str, Enum):
    FIRST_CAPTURE = "FIRST_CAPTURE"
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"


class AdmissionDecision(str, Enum):
    ADMITTED = "ADMITTED"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    NONE = "NONE"
    DOCUMENT_MISMATCH = "DOCUMENT_MISMATCH"
    DOCUMENT_EXPIRED = "DOCUMENT_EXPIRED"
    BIOMETRIC_MISMATCH = "BIOMETRIC_MISMATCH"
    LATE_ARRIVAL = "LATE_ARRIVAL"


class IrregularityCategory(str, Enum):
    SEATING_VIOLATION = "SEATING_VIOLATION"
    PROHIBITED_ITEM = "PROHIBITED_ITEM"
    BREAK_VIOLATION = "BREAK_VIOLATION"
    SUSPECTED_IMPERSONATION = "SUSPECTED_IMPERSONATION"
    CONTENT_EXPOSURE = "CONTENT_EXPOSURE"


class IrregularitySeverity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


class IrregularityStatus(str, Enum):
    FILED = "FILED"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class ScoreStatus(str, Enum):
    PENDING_ANALYSIS = "PENDING_ANALYSIS"
    UNDER_REVIEW = "UNDER_REVIEW"
    VALIDATED = "VALIDATED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class TriggerReason(str, Enum):
    ANOMALOUS_GAIN = "ANOMALOUS_GAIN"
    RESPONSE_SIMILARITY = "RESPONSE_SIMILARITY"
    CONTENT_EXPOSURE = "CONTENT_EXPOSURE"


class CaseStatus(str, Enum):
    OPENED = "OPENED"
    NOTIFIED = "NOTIFIED"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    WINDOW_EXPIRED = "WINDOW_EXPIRED"
    ADJUDICATED_UPHELD = "ADJUDICATED_UPHELD"
    ADJUDICATED_CANCELLED = "ADJUDICATED_CANCELLED"


class AdjudicationOutcome(str, Enum):
    NONE = "NONE"
    UPHELD = "UPHELD"
    CANCELLED = "CANCELLED"


class ReportStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"
    RECALLED = "RECALLED"


class AccommodationType(str, Enum):
    EXTENDED_TIME = "EXTENDED_TIME"
    SCREEN_READER = "SCREEN_READER"
    LARGE_PRINT = "LARGE_PRINT"
    SEPARATE_ROOM = "SEPARATE_ROOM"


class AccommodationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class TestCenter(TypedDict, total=False):
    id: str
    name: str
    facility_seat_capacity: int
    equipment_list: List[str]
    authorization_status: str
    last_audit_outcome: str
    active_staff_count: int
    created_at: str
    updated_at: str
    version: int


class Staff(TypedDict, total=False):
    id: str
    center_id: str
    full_name: str
    staff_role: str
    certification_level: str
    created_at: str
    updated_at: str
    version: int


class CenterAudit(TypedDict, total=False):
    id: str
    center_id: str
    scheduled_date: str
    audit_type: str
    status: str
    facility_findings: int
    staffing_findings: int
    equipment_findings: int
    high_severity_findings: int
    compliance_score: int
    outcome: str
    created_at: str
    updated_at: str
    version: int


class TestSession(TypedDict, total=False):
    id: str
    center_id: str
    test_date: str
    start_time: str
    end_time: str
    room_label: str
    total_seats: int
    reserved_accommodation_seats: int
    status: str
    proctor_staff_ids: List[str]
    confirmed_count: int
    waitlist_count: int
    effective_general_cap: int
    created_at: str
    updated_at: str
    version: int


class Examinee(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    id_document_type: str
    id_document_number: str
    id_document_expiry: str
    biometric_template_ref: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict, total=False):
    id: str
    session_id: str
    examinee_id: str
    booking_status: str
    attendance_status: str
    requires_accommodation_seat: bool
    pool: str
    waitlist_position: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CheckInRecord(TypedDict, total=False):
    # Immutable evidentiary artifact: carries only id + created_at (PRD §2.4).
    id: str
    registration_id: str
    recorded_by_staff_id: str
    document_check_result: str
    biometric_result: str
    admission_decision: str
    denial_reason: str
    created_at: str


class IrregularityReport(TypedDict, total=False):
    id: str
    registration_id: str
    session_id: str
    reported_by_staff_id: str
    category: str
    severity: str
    narrative: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScoreRecord(TypedDict, total=False):
    id: str
    registration_id: str
    section_raws: List[int]
    prior_best_scaled_score: int
    matched_responses_count: int
    total_scored_items: int
    same_form: bool
    adjacent_seated: bool
    raw_total: int
    provisional_scaled_score: int
    scaled_score: Optional[int]
    status: str
    released_report_count: int
    created_at: str
    updated_at: str
    version: int


class ScoreReviewCase(TypedDict, total=False):
    id: str
    registration_id: str
    trigger_reason: str
    flagged_by_analyst_id: str
    status: str
    response_deadline: Optional[str]
    examinee_response: Optional[str]
    adjudicator_id: Optional[str]
    adjudication_rationale: Optional[str]
    adjudication_outcome: str
    created_at: str
    updated_at: str
    version: int


class ScoreReport(TypedDict, total=False):
    id: str
    score_record_id: str
    institution_code: str
    status: str
    hold_until: Optional[str]
    released_at: Optional[str]
    recalled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccommodationRequest(TypedDict, total=False):
    id: str
    examinee_id: str
    accommodation_type: str
    requires_alternate_format: bool
    status: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int
