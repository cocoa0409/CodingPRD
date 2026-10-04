"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class QuestionSetStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class WaveStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FINALIZED = "FINALIZED"


class InvitationStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"
    OPTED_OUT = "OPTED_OUT"
    SUPPRESSED = "SUPPRESSED"


class ResponseStatus(str, Enum):
    SCORED = "SCORED"
    FLAGGED = "FLAGGED"
    EXCLUDED = "EXCLUDED"


class ExcludedReason(str, Enum):
    APPEAL_UPHELD = "APPEAL_UPHELD"
    MANIPULATION_CONFIRMED = "MANIPULATION_CONFIRMED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class FlagStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class FlagKind(str, Enum):
    COACHING = "COACHING"
    OPT_OUT_SUPPRESSION = "OPT_OUT_SUPPRESSION"
    CONTACT_TAMPERING = "CONTACT_TAMPERING"


class StatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    PAID = "PAID"
    SUPERSEDED = "SUPERSEDED"


class StatementTier(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"
    INELIGIBLE = "INELIGIBLE"


class ActionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"


class DealerPosture(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class DepartmentKind(str, Enum):
    SALES = "SALES"
    SERVICE = "SERVICE"


class TransactionKind(str, Enum):
    SALE = "SALE"
    SERVICE_VISIT = "SERVICE_VISIT"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    REGIONAL_MANAGER = "RegionalManager"
    FIELD_CONSULTANT = "FieldConsultant"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    SURVEY_VENDOR = "SurveyVendor"
    DEALER_PRINCIPAL = "DealerPrincipal"
    CUSTOMER = "Customer"


class Region(TypedDict, total=False):
    id: str
    code: str
    name: str
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict, total=False):
    id: str
    region_id: str
    name: str
    dealer_code: str
    posture: str
    current_score_adjusted: Optional[float]
    current_response_rate: Optional[float]
    confirmed_flag_count: int
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict, total=False):
    id: str
    dealer_id: str
    kind: str
    name: str
    created_at: str
    updated_at: str
    version: int


class Advisor(TypedDict, total=False):
    id: str
    department_id: str
    name: str
    employee_ref: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    do_not_contact: bool
    created_at: str
    updated_at: str
    version: int


class QuestionSet(TypedDict, total=False):
    id: str
    code: str
    questions: List[dict]
    comparability_factor: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveyWave(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    question_set_id: str
    status: str
    closed_at: Optional[str]
    invitations_total: int
    queued_count: int
    sent_count: int
    responded_count: int
    expired_count: int
    opted_out_count: int
    suppressed_count: int
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict, total=False):
    # Immutable record: carries ONLY id + created_at (no updated_at, no version)
    id: str
    dealer_id: str
    department_id: str
    advisor_id: Optional[str]
    customer_id: str
    kind: str
    completed_at: str
    margin_cents: int
    created_at: str


class SurveyInvitation(TypedDict, total=False):
    id: str
    transaction_id: str
    customer_id: str
    wave_id: str
    question_set_id: str
    status: str
    sent_at: Optional[str]
    window_closes_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveyResponse(TypedDict, total=False):
    id: str
    invitation_id: str
    answers: List[dict]
    score: float
    status: str
    excluded_reason: Optional[str]
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    response_id: str
    dealer_id: str
    reason: str
    status: str
    decision_rationale: Optional[str]
    prior_response_status: str
    created_at: str
    updated_at: str
    version: int


class ManipulationFlag(TypedDict, total=False):
    id: str
    dealer_id: str
    response_id: Optional[str]
    kind: str
    evidence: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IncentiveStatement(TypedDict, total=False):
    id: str
    dealer_id: str
    wave_id: str
    status: str
    supersedes_id: Optional[str]
    score_used: Optional[float]
    response_rate_used: Optional[float]
    tier: str
    eligible_margin_cents: int
    payout_cents: int
    created_at: str
    updated_at: str
    version: int


class ActionPlan(TypedDict, total=False):
    id: str
    dealer_id: str
    wave_id: str
    title: str
    items: List[dict]
    due_date: str
    status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
