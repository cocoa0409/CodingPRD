"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ADMISSIONS_COUNSELOR = "AdmissionsCounselor"
    ELIGIBILITY_REVIEWER = "EligibilityReviewer"
    ENROLLMENT_MANAGER = "EnrollmentManager"
    RESIDENTIAL_ADVISOR = "ResidentialAdvisor"
    CAREER_INSTRUCTOR = "CareerInstructor"
    TRANSITION_SPECIALIST = "TransitionSpecialist"
    OPERATOR_ADMIN = "OperatorAdmin"


class AssignmentStatus(str, Enum):
    NONE = "NONE"
    ASSIGNED = "ASSIGNED"
    ENROLLED = "ENROLLED"
    RELEASED = "RELEASED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class DeterminationReason(str, Enum):
    AGE_OUT_OF_RANGE = "AGE_OUT_OF_RANGE"
    INCOME_EXCEEDS_LIMIT = "INCOME_EXCEEDS_LIMIT"
    NO_BARRIER_DOCUMENTED = "NO_BARRIER_DOCUMENTED"


class BarrierFlag(str, Enum):
    FOSTER_CARE = "FOSTER_CARE"
    HOMELESS = "HOMELESS"
    SINGLE_PARENT = "SINGLE_PARENT"
    DISABILITY = "DISABILITY"
    OFFENDER = "OFFENDER"
    LOW_BASIC_SKILLS = "LOW_BASIC_SKILLS"


class TradeProgramStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class TrainingStatus(str, Enum):
    REMEDIATION = "REMEDIATION"
    TRAINING = "TRAINING"
    COMPLETED = "COMPLETED"
    UNENROLLED = "UNENROLLED"
    SEPARATED = "SEPARATED"


class ResidentialStatus(str, Enum):
    NONRESIDENTIAL = "NONRESIDENTIAL"
    AWAITING_BED = "AWAITING_BED"
    RESIDENT = "RESIDENT"
    RELEASED = "RELEASED"


class DormitoryAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CHECKED_OUT = "CHECKED_OUT"
    TERMINATED = "TERMINATED"


class InfractionCode(str, Enum):
    CURFEW_VIOLATION = "CURFEW_VIOLATION"
    THEFT = "THEFT"
    VIOLENCE = "VIOLENCE"
    DRUGS = "DRUGS"
    WEAPONS = "WEAPONS"
    OTHER = "OTHER"


class ConductIncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    INVESTIGATING = "INVESTIGATING"
    DISMISSED = "DISMISSED"
    SANCTIONED = "SANCTIONED"
    BOARD_REVIEW = "BOARD_REVIEW"
    EXONERATED = "EXONERATED"
    SEPARATION_ORDERED = "SEPARATION_ORDERED"


class CredentialType(str, Enum):
    HSE = "HSE"
    INDUSTRY_CERT = "INDUSTRY_CERT"
    DRIVER_LICENSE = "DRIVER_LICENSE"


class CredentialStatus(str, Enum):
    EARNED = "EARNED"
    VERIFIED = "VERIFIED"
    REVOKED = "REVOKED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class WBLPlacementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class TransitionPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class ServiceTrackStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"


class ServiceType(str, Enum):
    JOB_PLACEMENT = "JOB_PLACEMENT"
    HOUSING = "HOUSING"
    TRANSPORTATION = "TRANSPORTATION"


class OperatorContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    TERMINATED = "TERMINATED"


class SnapshotVariant(str, Enum):
    FINAL = "FINAL"
    PROVISIONAL = "PROVISIONAL"


class Applicant(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    home_region_code: str
    desired_trade_code: str
    assigned_center_id: Optional[str]
    assignment_status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    applicant_id: str
    intake_counselor_id: str
    reviewer_id: Optional[str]
    household_size: int
    annual_income_cents: int
    barrier_flags: List[str]
    status: str
    determination_reasons: List[str]
    determined_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Center(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    total_beds: int
    beds_in_use: int
    beds_available: int
    created_at: str
    updated_at: str
    version: int


class TradeProgram(TypedDict, total=False):
    id: str
    center_id: str
    trade_code: str
    capacity: int
    required_credential_types: List[str]
    supports_remediation: bool
    enrolled_count: int
    open_seats: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    applicant_id: str
    trade_program_id: str
    residential_track: bool
    training_status: str
    residential_status: str
    conduct_hold: bool
    exit_date: Optional[str]
    exit_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DormitoryAssignment(TypedDict, total=False):
    id: str
    enrollment_id: str
    bed_label: str
    move_in_date: str
    move_out_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConductIncident(TypedDict, total=False):
    id: str
    enrollment_id: str
    infraction_code: str
    zero_tolerance: bool
    sanction_points: Optional[int]
    occurred_at: str
    note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Credential(TypedDict, total=False):
    id: str
    enrollment_id: str
    credential_type: str
    subject_area: Optional[str]
    status: str
    earned_at: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmployerAgreement(TypedDict, total=False):
    id: str
    employer_name: str
    trade_code: str
    region_code: str
    slot_count: int
    hourly_wage_floor_cents: int
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WBLPlacement(TypedDict, total=False):
    id: str
    enrollment_id: str
    employer_agreement_id: str
    supervisor_id: str
    hourly_wage_cents: int
    verified_hours_total: int
    provisional_hours_total: int
    status: str
    start_date: Optional[str]
    converted_to_hire: bool
    hire_wage_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TransitionPlan(TypedDict, total=False):
    id: str
    enrollment_id: str
    separation_date: str
    expires_at: str
    status: str
    job_placement_status: str
    housing_status: str
    transportation_status: str
    job_starting_wage_cents: Optional[int]
    housing_stipend_cents: int
    transport_allowance_cents: int
    created_at: str
    updated_at: str
    version: int


class OperatorContract(TypedDict, total=False):
    id: str
    center_id: str
    operator_name: str
    contract_code: str
    status: str
    current_period_start: str
    period_sequence: int
    created_at: str
    updated_at: str
    version: int


class PerformanceSnapshot(TypedDict, total=False):
    """Immutable historical record: carries only id + created_at of the common
    fields (PRD section 2.5) — no updated_at, no version."""
    id: str
    contract_id: str
    variant: str
    period_start: str
    period_end: str
    graduates_count: int
    leavers_count: int
    graduation_rate: float
    placement_rate: float
    avg_starting_wage_cents: int
    payment_cents: int
    created_at: str
