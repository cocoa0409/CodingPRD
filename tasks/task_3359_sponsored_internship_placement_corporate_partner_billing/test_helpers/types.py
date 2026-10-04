"""Domain types for the Sponsored Internship Placement API.

Every resource described in the PRD is fully mutable and therefore exposes
both ``updated_at`` and ``version`` alongside ``id`` and ``created_at``
(PRD §2.4).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PROGRAM_STAFF = "ProgramStaff"
    PARTNER = "Partner"
    STUDENT = "Student"


class Industry(str, Enum):
    TECH = "TECH"
    FINANCE = "FINANCE"
    HEALTHCARE = "HEALTHCARE"
    RETAIL = "RETAIL"
    LOGISTICS = "LOGISTICS"


class FeeTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class EducationStatus(str, Enum):
    NO_DIPLOMA = "NO_DIPLOMA"
    HS_DIPLOMA = "HS_DIPLOMA"
    SOME_COLLEGE = "SOME_COLLEGE"
    ASSOCIATE = "ASSOCIATE"
    BACHELOR_OR_HIGHER = "BACHELOR_OR_HIGHER"


class ApplicationState(str, Enum):
    APPLIED = "APPLIED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    ENROLLED = "ENROLLED"


class ProgramPhase(str, Enum):
    L_AND_D = "L_AND_D"
    INTERNSHIP = "INTERNSHIP"
    COMPLETED = "COMPLETED"


class TrackCode(str, Enum):
    SOFTWARE = "SOFTWARE"
    DATA = "DATA"
    CYBER = "CYBER"
    IT_SUPPORT = "IT_SUPPORT"


class RosterStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    PROBATION = "PROBATION"
    DISMISSED = "DISMISSED"


class CohortStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"


class PlacementState(str, Enum):
    MATCHED = "MATCHED"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    INTERVIEWED = "INTERVIEWED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class InterviewOutcome(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ConversionOutcome(str, Enum):
    CONVERTED = "CONVERTED"
    NOT_CONVERTED = "NOT_CONVERTED"


class StipendPhase(str, Enum):
    L_AND_D = "L_AND_D"
    INTERNSHIP = "INTERNSHIP"


class StipendStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    VOID = "VOID"


class CreditGrantStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    VOID = "VOID"


class EmploymentStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    EMPLOYED = "EMPLOYED"
    UNEMPLOYED = "UNEMPLOYED"
    ENROLLED_EDUCATION = "ENROLLED_EDUCATION"


class Partner(TypedDict, total=False):
    id: str
    legal_name: str
    industry: str
    billing_email: str
    status: str
    fee_tier: str
    placement_quality_score: float
    on_time_payment_ratio: float
    credit_hold: bool
    outstanding_balance_cents: int
    billed_cents: int
    collected_cents: int
    collection_ratio: float
    oldest_open_due_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    education_status: str
    household_income_cents: int
    application_state: str
    current_phase: Optional[str]
    track_code: Optional[str]
    graduation_at: Optional[str]
    total_stipend_paid_cents: int
    lifetime_contract_points: int
    conversion_streak: int
    roster_status: str
    created_at: str
    updated_at: str
    version: int


class Cohort(TypedDict, total=False):
    id: str
    program_code: str
    location_code: str
    start_date: str
    capacity: int
    enrolled_count: int
    graduation_date: str
    awarded_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict, total=False):
    id: str
    partner_id: str
    project_scope: str
    supervision_hours_per_week: int
    slot_count: int
    fee_tier: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InternshipPlacement(TypedDict, total=False):
    id: str
    agreement_id: str
    student_id: str
    state: str
    interview_attempt: int
    max_interview_rounds: int
    start_date: Optional[str]
    end_date: Optional[str]
    hours_per_week: Optional[int]
    placement_fee_cents: Optional[int]
    project_scope: str
    supervisor_name: str
    outcome: Optional[str]
    satisfaction_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class InterviewRound(TypedDict, total=False):
    id: str
    placement_id: str
    scheduled_for: str
    duration_minutes: int
    supervisor_name: str
    round_number: int
    outcome: str
    feedback: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StipendStatement(TypedDict, total=False):
    id: str
    student_id: str
    phase: str
    period_start: str
    period_end: str
    hours_attended: int
    hours_expected: int
    attendance_ratio: float
    behavior_incidents: int
    contract_points_earned: int
    gross_amount_cents: int
    attendance_deduction_cents: int
    behavior_deduction_cents: int
    net_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SatisfactionRecord(TypedDict, total=False):
    id: str
    placement_id: str
    supervisor_rating: float
    project_rating: float
    communication_rating: float
    composite_score: float
    submitted_at: str
    converted_to_hire: bool
    created_at: str
    updated_at: str
    version: int


class OutcomeCheckpoint(TypedDict, total=False):
    id: str
    student_id: str
    interval_months: int
    due_date: str
    employment_status: str
    hourly_wage_cents: Optional[int]
    recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    partner_id: str
    placement_id: str
    total_amount_cents: int
    amount_paid_cents: int
    due_date: str
    paid_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditGrant(TypedDict, total=False):
    id: str
    student_id: str
    college_partner_name: str
    credit_hours: float
    tuition_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
