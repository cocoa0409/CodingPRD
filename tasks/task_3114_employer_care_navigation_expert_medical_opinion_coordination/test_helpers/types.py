"""Domain types: entity shapes, status enums, role enum for the care navigation API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    EMPLOYER_ADMIN = "EmployerAdmin"
    MEMBER = "Member"
    NURSE_NAVIGATOR = "NurseNavigator"
    CARE_ADVOCATE = "CareAdvocate"
    PHYSICIAN_ADVISOR = "PhysicianAdvisor"
    RECORDS_SPECIALIST = "RecordsSpecialist"
    EXPERT_REVIEWER = "ExpertReviewer"
    BILLING_ADVOCATE = "BillingAdvocate"
    PLAN_ADMINISTRATOR = "PlanAdministrator"


class MemberRelationship(str, Enum):
    SELF = "SELF"
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"


class EligibilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CoverageTier(str, Enum):
    EMPLOYEE_ONLY = "EMPLOYEE_ONLY"
    EMPLOYEE_SPOUSE = "EMPLOYEE_SPOUSE"
    EMPLOYEE_CHILDREN = "EMPLOYEE_CHILDREN"
    FAMILY = "FAMILY"


class CoverageWindowStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class NetworkStatus(str, Enum):
    IN_NETWORK = "IN_NETWORK"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"


class ConsentScope(str, Enum):
    RECORD_RETRIEVAL = "RECORD_RETRIEVAL"
    APPOINTMENT_BOOKING = "APPOINTMENT_BOOKING"
    EMO_REVIEW = "EMO_REVIEW"
    BILLING_ADVOCACY = "BILLING_ADVOCACY"


class ConsentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class QuestionType(str, Enum):
    CLINICAL = "CLINICAL"
    BENEFIT = "BENEFIT"
    COST = "COST"


class Acuity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Discipline(str, Enum):
    NURSE = "NURSE"
    ADVOCATE = "ADVOCATE"
    PHYSICIAN = "PHYSICIAN"


class NavigationCaseStatus(str, Enum):
    ROUTED = "ROUTED"
    IN_PROGRESS = "IN_PROGRESS"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class RecordRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ExpertOpinionStatus(str, Enum):
    INTAKE = "INTAKE"
    RECORDS_COLLECTION = "RECORDS_COLLECTION"
    COMPILING = "COMPILING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    RECOMMENDATION_SUBMITTED = "RECOMMENDATION_SUBMITTED"
    RECORDS_BLOCKED = "RECORDS_BLOCKED"
    AUTH_BLOCKED = "AUTH_BLOCKED"
    DELIVERED = "DELIVERED"
    WITHDRAWN = "WITHDRAWN"


class ErrorFlag(str, Enum):
    NONE = "NONE"
    DUPLICATE = "DUPLICATE"
    UPCODING = "UPCODING"


class ClaimStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ADJUDICATED = "ADJUDICATED"
    VOID = "VOID"


class BillingCaseStatus(str, Enum):
    OPENED = "OPENED"
    ERROR_IDENTIFIED = "ERROR_IDENTIFIED"
    NEGOTIATING = "NEGOTIATING"
    SETTLEMENT_PROPOSED = "SETTLEMENT_PROPOSED"
    RESOLVED_ACCEPTED = "RESOLVED_ACCEPTED"
    RESOLVED_NO_CHANGE = "RESOLVED_NO_CHANGE"
    VOIDED = "VOIDED"
    CLOSED = "CLOSED"


class ServiceCode(str, Enum):
    EXPERT_MEDICAL_OPINION = "EXPERT_MEDICAL_OPINION"
    PROCEDURE = "PROCEDURE"
    IMAGING = "IMAGING"


class AuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    DENIED_FINAL = "DENIED_FINAL"


class Employer(TypedDict, total=False):
    id: str
    name: str
    pepm_fee_cents: int
    avg_in_out_cost_delta_cents: int
    emo_benefit_enabled: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    employer_id: str
    subscriber_id: Optional[str]
    relationship: str
    full_name: str
    date_of_birth: str
    external_member_ref: str
    eligibility_status: str
    deductible_limit_cents: int
    oop_max_cents: int
    deductible_used_cents: int
    oop_used_cents: int
    created_at: str
    updated_at: str
    version: int


class CoverageWindow(TypedDict, total=False):
    id: str
    member_id: str
    coverage_tier: str
    effective_start: str
    effective_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    name: str
    specialty: str
    network_status: str
    created_at: str
    updated_at: str
    version: int


class QualitySnapshot(TypedDict, total=False):
    id: str
    provider_id: str
    period_start: str
    period_end: str
    outcome_score: float
    cost_efficiency_score: float
    access_score: float
    claims_volume: int
    composite_quality_score: float
    created_at: str
    updated_at: str
    version: int


class ProviderMatch(TypedDict, total=False):
    """Ephemeral computed view: id + created_at only, no updated_at/version."""
    id: str
    created_at: str
    provider_id: str
    provider_name: str
    specialty: str
    network_status: str
    composite_quality_score: float
    network_factor: float
    match_score: float
    rank: int


class ConsentGrant(TypedDict, total=False):
    id: str
    member_id: str
    scope: str
    expires_at: str
    status: str
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NavigationCase(TypedDict, total=False):
    id: str
    member_id: str
    question_type: str
    acuity: Optional[str]
    estimated_cost_cents: Optional[int]
    routed_discipline: str
    assigned_user_id: Optional[str]
    escalation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    member_id: str
    provider_id: str
    navigation_case_id: Optional[str]
    slot_start: str
    slot_end: str
    redirected_from_out_of_network: bool
    status: str
    booked_by_user_id: str
    late_cancel: bool
    created_at: str
    updated_at: str
    version: int


class RecordRequest(TypedDict, total=False):
    id: str
    member_id: str
    provider_id: str
    status: str
    record_pages: Optional[int]
    retry_count: int
    created_at: str
    updated_at: str
    version: int


class ExpertOpinionCase(TypedDict, total=False):
    id: str
    member_id: str
    navigation_case_id: Optional[str]
    condition_summary: str
    status: str
    compiler_user_id: Optional[str]
    reviewer_user_id: Optional[str]
    recommendation_text: Optional[str]
    recommendation_version: int
    attached_received_count: int
    created_at: str
    updated_at: str
    version: int


class OpinionRecordItem(TypedDict, total=False):
    id: str
    opinion_id: str
    record_request_id: str
    attached_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict, total=False):
    line_code: str
    billed_cents: int
    schedule_rate: float
    error_flag: str


class Claim(TypedDict, total=False):
    id: str
    member_id: str
    provider_id: str
    service_date: str
    billed_amount_cents: int
    allowed_amount_cents: int
    lines: List[ClaimLine]
    repriced_total_cents: Optional[int]
    error_line_count: int
    deductible_applied_cents: Optional[int]
    member_responsibility_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingCase(TypedDict, total=False):
    id: str
    member_id: str
    claim_id: str
    status: str
    provisional_savings_cents: Optional[int]
    counter_offer_cents: Optional[int]
    settled_amount_cents: Optional[int]
    final_savings_cents: Optional[int]
    proposal_count: int
    created_at: str
    updated_at: str
    version: int


class PlanAuthorization(TypedDict, total=False):
    id: str
    member_id: str
    service_code: str
    units: int
    status: str
    denial_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
