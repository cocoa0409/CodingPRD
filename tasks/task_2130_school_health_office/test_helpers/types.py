"""Domain types for the School Health Office API: status enums, role enum, entity shapes."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    DISTRICT_HEALTH_ADMIN = "DistrictHealthAdmin"
    SCHOOL_NURSE = "SchoolNurse"
    HEALTH_AIDE = "HealthAide"
    GUARDIAN = "Guardian"
    SCHOOL_PHYSICIAN = "SchoolPhysician"
    RECORDS_OFFICER = "RecordsOfficer"


class CoveragePosture(str, Enum):
    FULL = "FULL"
    LIMITED = "LIMITED"
    UNCOVERED = "UNCOVERED"


class StockProtocolStatus(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    DEPLETED = "DEPLETED"


class NurseCredential(str, Enum):
    RN = "RN"
    LPN = "LPN"
    HEALTH_AIDE = "HEALTH_AIDE"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CoverageAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    TRANSFERRED = "TRANSFERRED"
    WITHDRAWN = "WITHDRAWN"


class RiskTier(str, Enum):
    ROUTINE = "ROUTINE"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class AlertFlag(str, Enum):
    ALLERGY_ANAPHYLAXIS = "ALLERGY_ANAPHYLAXIS"
    IMMUNIZATION_HOLD = "IMMUNIZATION_HOLD"
    NO_ACTIVE_PLAN = "NO_ACTIVE_PLAN"
    SCREENING_REFERRAL = "SCREENING_REFERRAL"
    SELF_CARRY = "SELF_CARRY"


class ActionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_GUARDIAN = "PENDING_GUARDIAN"
    PENDING_PROVIDER = "PENDING_PROVIDER"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ConsentStatus(str, Enum):
    CONSENT_PENDING = "CONSENT_PENDING"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    CONSENT_WITHDRAWN = "CONSENT_WITHDRAWN"


class ClinicalStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class VisitStatus(str, Enum):
    OPEN = "OPEN"
    IN_ASSESSMENT = "IN_ASSESSMENT"
    DISPOSITIONED = "DISPOSITIONED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class Disposition(str, Enum):
    RETURN_TO_CLASS = "RETURN_TO_CLASS"
    SEND_HOME = "SEND_HOME"
    EMS_TRANSPORT = "EMS_TRANSPORT"
    REFERRED_EXTERNAL = "REFERRED_EXTERNAL"


class AdministrationStatus(str, Enum):
    PREPARED = "PREPARED"
    ADMINISTERED = "ADMINISTERED"
    REFUSED = "REFUSED"
    WASTED = "WASTED"
    VOIDED = "VOIDED"


class ProtocolMode(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    STOCK_EMERGENCY = "STOCK_EMERGENCY"


class ScreeningStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    RESCREEN_DUE = "RESCREEN_DUE"
    REFERRED = "REFERRED"
    CLOSED = "CLOSED"
    DECLINED = "DECLINED"


class ScreeningOutcome(str, Enum):
    PASS = "PASS"
    REFER = "REFER"
    INCONCLUSIVE = "INCONCLUSIVE"


class DisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    CONSENT_PENDING = "CONSENT_PENDING"
    AWAITING_DECISION = "AWAITING_DECISION"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class RedactionLevel(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class School(TypedDict):
    id: str
    name: str
    building_code: str
    cot_capacity: int
    emergency_protocol_enabled: bool
    enrolled_student_count: int
    eligible_stock_student_count: int
    base_required_units: int
    surge_units: int
    required_stock_units: int
    contracted_weekly_minutes: int
    delivered_weekly_minutes: float
    contracted_students_per_nurse_fte: Optional[float]
    delivered_students_per_nurse_fte: Optional[float]
    coverage_posture: str
    epinephrine_days_of_supply: float
    albuterol_days_of_supply: float
    stock_protocol_status: str
    occupied_cot_count: int
    created_at: str
    updated_at: str
    version: int


class Nurse(TypedDict):
    id: str
    full_name: str
    credential: str
    delegation_authorized: bool
    weekly_contracted_minutes: int
    committed_weekly_minutes: int
    uncommitted_weekly_minutes: int
    assigned_school_count: int
    employment_status: str
    created_at: str
    updated_at: str
    version: int


class CoverageAssignment(TypedDict):
    id: str
    nurse_id: str
    school_id: str
    weekday: str
    start_minute: int
    end_minute: int
    effective_from: str
    effective_to: Optional[str]
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    school_id: str
    full_name: str
    grade_level: int
    date_of_birth: str
    allergy_severity: str
    chronic_condition_codes: List[str]
    immunization_status: str
    privacy_hold: bool
    enrollment_status: str
    intake_risk_score: int
    observed_risk_score: int
    effective_risk_score: int
    risk_tier: str
    alert_flags: List[str]
    self_carry_authorized: bool
    active_action_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ActionPlan(TypedDict):
    id: str
    student_id: str
    supersedes_action_plan_id: Optional[str]
    condition_code: str
    severity_score: int
    requires_stock_epinephrine: bool
    self_carry_requested: bool
    effective_from: str
    review_due_at: Optional[str]
    guardian_consent_at: Optional[str]
    provider_signed_at: Optional[str]
    revision_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicationAuthorization(TypedDict):
    id: str
    student_id: str
    action_plan_id: Optional[str]
    medication_code: str
    route: str
    dose_amount: float
    dose_unit: str
    schedule_type: str
    prn_min_interval_minutes: Optional[int]
    max_doses_per_day: int
    valid_from: str
    valid_until: str
    is_controlled: bool
    consent_status: str
    clinical_status: str
    dispensable: bool
    doses_administered_today: int
    last_administered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MedicationStockLot(TypedDict):
    id: str
    school_id: str
    medication_code: str
    lot_number: str
    is_stock_protocol: bool
    expiration_date: str
    received_total: int
    quantity_on_hand: int
    quantity_reserved: int
    quantity_administered: int
    quantity_wasted: int
    quantity_available: int
    days_of_supply: float
    status: str
    created_at: str
    updated_at: str
    version: int


class HealthVisit(TypedDict):
    id: str
    student_id: str
    school_id: str
    nurse_id: str
    complaint_code: str
    acuity: str
    assessment_note: Optional[str]
    arrival_at: str
    closed_at: Optional[str]
    triage_score: int
    requires_ems_review: bool
    disposition: Optional[str]
    guardian_notified: bool
    reopen_count: int
    pending_administration_count: int
    minutes_in_office: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdministrationRecord(TypedDict):
    id: str
    visit_id: str
    authorization_id: Optional[str]
    lot_id: str
    administering_nurse_id: str
    witness_nurse_id: Optional[str]
    medication_code: str
    units: int
    dose_amount: float
    protocol_mode: str
    reason_code: Optional[str]
    prepared_at: str
    administered_at: Optional[str]
    voided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Screening(TypedDict):
    id: str
    student_id: str
    school_id: str
    screened_by_nurse_id: Optional[str]
    screening_type: str
    scheduled_for: str
    cycle_number: int
    result_value: Optional[float]
    outcome: Optional[str]
    rescreen_due_at: Optional[str]
    referral_due_at: Optional[str]
    referral_completed_at: Optional[str]
    referral_outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisclosureRequest(TypedDict):
    id: str
    student_id: str
    requester_type: str
    requester_reference: str
    scope: List[str]
    purpose_code: str
    consent_granted_at: Optional[str]
    expires_at: Optional[str]
    released_at: Optional[str]
    decided_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    redaction_level: str
    release_package_item_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
