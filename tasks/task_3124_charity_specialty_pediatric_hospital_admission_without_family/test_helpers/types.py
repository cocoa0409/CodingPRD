"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


# --- status enums ---

class HospitalStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProgramCategory(str, Enum):
    ORTHOPEDIC = "ORTHOPEDIC"
    BURN = "BURN"
    CLEFT_CRANIOFACIAL = "CLEFT_CRANIOFACIAL"
    SPINAL_CORD = "SPINAL_CORD"
    NEUROMUSCULAR = "NEUROMUSCULAR"


class ConditionCategory(str, Enum):
    ORTHOPEDIC = "ORTHOPEDIC"
    BURN = "BURN"
    CLEFT_CRANIOFACIAL = "CLEFT_CRANIOFACIAL"
    SPINAL_CORD = "SPINAL_CORD"
    NEUROMUSCULAR = "NEUROMUSCULAR"
    OTHER = "OTHER"


class ReferralSourceType(str, Enum):
    COMMUNITY_PHYSICIAN = "COMMUNITY_PHYSICIAN"
    OUTREACH_CLINIC = "OUTREACH_CLINIC"
    INTERNATIONAL_PARTNER = "INTERNATIONAL_PARTNER"


class ReferralSourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FamilyAbilityToPay(str, Enum):
    UNABLE = "UNABLE"
    PARTIAL = "PARTIAL"
    ABLE = "ABLE"
    DECLINED_TO_STATE = "DECLINED_TO_STATE"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PENDING_REVIEW = "PENDING_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ReviewAction(str, Enum):
    OPEN_ROUND = "OPEN_ROUND"
    REQUEST_INFO = "REQUEST_INFO"
    CAST_VOTE_ACCEPT = "CAST_VOTE_ACCEPT"
    CAST_VOTE_DENY = "CAST_VOTE_DENY"
    RESUBMIT_INFO = "RESUBMIT_INFO"


class InsurancePolicyStatus(str, Enum):
    VERIFIED = "VERIFIED"
    LAPSED = "LAPSED"


class BillingAccountStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    DENIED_CLAIM = "DENIED_CLAIM"


class ClinicalStatus(str, Enum):
    PLANNING = "PLANNING"
    ACTIVE_TREATMENT = "ACTIVE_TREATMENT"
    SURVEILLANCE = "SURVEILLANCE"
    DISCHARGED = "DISCHARGED"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    FULLY_FUNDED = "FULLY_FUNDED"


class StageStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    DEFERRED = "DEFERRED"
    CANCELLED_STAGE = "CANCELLED_STAGE"


class GrantType(str, Enum):
    TRAVEL = "TRAVEL"
    LODGING = "LODGING"
    TRAVEL_AND_LODGING = "TRAVEL_AND_LODGING"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    REVOKED = "REVOKED"


class ClinicStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED_CLINIC = "CANCELLED_CLINIC"


class ScreeningStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CONVERTED = "CONVERTED"
    NO_SHOW = "NO_SHOW"
    EXPIRED = "EXPIRED"


class FundStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class AllocationStatus(str, Enum):
    PLEDGED = "PLEDGED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"


class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    REFERRING_PHYSICIAN = "ReferringPhysician"
    REVIEW_COMMITTEE_MEMBER = "ReviewCommitteeMember"
    BILLING_SPECIALIST = "BillingSpecialist"
    CARE_COORDINATOR = "CareCoordinator"
    OUTREACH_PLANNER = "OutreachPlanner"
    PHILANTHROPY_OFFICER = "PhilanthropyOfficer"


# --- entity TypedDicts (common_fields: true unless noted) ---

class SpecialtyHospital(TypedDict):
    id: str
    hospital_code: str
    name: str
    city: str
    state_code: str
    latitude: float
    longitude: float
    annual_capacity: int
    admissions_ytd: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialtyProgram(TypedDict):
    id: str
    hospital_id: str
    category: str
    accepts_international: bool
    min_age_months: int
    max_age_months: int
    staged_care_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ReferralSource(TypedDict):
    id: str
    source_type: str
    display_name: str
    contact_email: str
    country_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PatientApplication(TypedDict):
    id: str
    patient_full_name: str
    patient_date_of_birth: str
    condition_category: str
    referral_source_id: str
    program_id: str
    screening_id: Optional[str]
    home_latitude: float
    home_longitude: float
    is_international: bool
    family_ability_to_pay: str
    review_round: int
    info_requested_by: Optional[str]
    decision_reason: Optional[str]
    age_at_submission_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only review log: id + created_at only,
# NO updated_at, NO version.
class ApplicationReview(TypedDict):
    id: str
    application_id: str
    round_number: int
    reviewer_user_id: str
    action: str
    vote_weight: int
    created_at: str


class InsurancePolicy(TypedDict):
    id: str
    application_id: str
    payer_name: str
    policy_number: str
    coverage_exists: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingAccount(TypedDict):
    id: str
    application_id: str
    insurance_policy_id: Optional[str]
    total_charged_cents: int
    insurance_paid_cents: int
    charity_writeoff_cents: int
    family_balance_cents: int
    open_claim_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    billing_account_id: str
    service_date: str
    lines: list
    submitted_amount_cents: int
    estimated_allowed_cents: int
    adjudicated_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict):
    id: str
    application_id: str
    diagnosis_summary: str
    clinical_status: str
    funding_status: str
    planned_stage_count: int
    completed_stage_count: int
    created_at: str
    updated_at: str
    version: int


class StagedProcedure(TypedDict):
    id: str
    care_plan_id: str
    stage_index: int
    min_age_months: int
    max_age_months: int
    scheduled_date: str
    estimated_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TravelSupportGrant(TypedDict):
    id: str
    application_id: str
    grant_type: str
    straight_line_distance_miles: float
    road_distance_miles: float
    distance_eligible: bool
    nightly_lodging_stipend_cents: int
    travel_allowance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OutreachClinic(TypedDict):
    id: str
    hospital_id: str
    location_name: str
    latitude: float
    longitude: float
    start_date: str
    end_date: str
    screening_capacity: int
    booked_screening_count: int
    conversion_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OutreachScreening(TypedDict):
    id: str
    clinic_id: str
    patient_full_name: str
    patient_date_of_birth: str
    suspected_condition_category: str
    screening_date: str
    converted_application_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PhilanthropicFund(TypedDict):
    id: str
    fund_name: str
    fiscal_year: int
    total_committed_cents: int
    allocated_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundAllocation(TypedDict):
    id: str
    fund_id: str
    hospital_id: str
    program_id: Optional[str]
    care_plan_id: Optional[str]
    amount_cents: int
    allocation_weight: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int
