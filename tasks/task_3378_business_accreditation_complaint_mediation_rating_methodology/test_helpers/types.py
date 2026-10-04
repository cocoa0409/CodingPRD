"""Domain types: entity TypedDicts, status enums, role enum.

Every entity carries the four system-managed properties of PRD §2.5
(id, created_at, updated_at, version); all TypedDicts below include them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    BUREAU_ADMIN = "BureauAdmin"
    STANDARDS_REVIEWER = "StandardsReviewer"
    BUSINESS_REP = "BusinessRep"
    CONSUMER = "Consumer"


# ---------------------------------------------------------------------------
# Enums (PRD §3)
# ---------------------------------------------------------------------------
class SizeTier(str, Enum):
    MICRO = "MICRO"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class AccreditationStatus(str, Enum):
    NOT_ACCREDITED = "NOT_ACCREDITED"
    ACCREDITED = "ACCREDITED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class AdvertisingComplianceStatus(str, Enum):
    CLEAR = "CLEAR"
    UNDER_AD_REVIEW = "UNDER_AD_REVIEW"
    REFERRED_TO_REGULATOR = "REFERRED_TO_REGULATOR"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED_PENDING_DUES = "APPROVED_PENDING_DUES"
    ACCREDITED = "ACCREDITED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class BillingPlan(str, Enum):
    ANNUAL_PREPAID = "ANNUAL_PREPAID"
    QUARTERLY = "QUARTERLY"


class ChecklistResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ApplicationDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class DuesInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class LedgerEntryKind(str, Enum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    FORWARDED = "FORWARDED"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    CONSUMER_REBUTTED = "CONSUMER_REBUTTED"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    UNANSWERED = "UNANSWERED"
    MEDIATION_OFFERED = "MEDIATION_OFFERED"
    IN_MEDIATION = "IN_MEDIATION"
    MEDIATION_RESOLVED = "MEDIATION_RESOLVED"
    MEDIATION_FAILED = "MEDIATION_FAILED"
    IN_ARBITRATION = "IN_ARBITRATION"
    ARBITRATED = "ARBITRATED"


class ComplaintCategory(str, Enum):
    SERVICE = "SERVICE"
    PRODUCT = "PRODUCT"
    BILLING = "BILLING"
    ADVERTISING = "ADVERTISING"
    DELIVERY = "DELIVERY"
    WARRANTY = "WARRANTY"
    OTHER = "OTHER"


class ComplaintResponseKind(str, Enum):
    BUSINESS_RESPONSE = "BUSINESS_RESPONSE"
    CONSUMER_REBUTTAL = "CONSUMER_REBUTTAL"
    CONSUMER_ACCEPT = "CONSUMER_ACCEPT"
    CONSUMER_REJECT = "CONSUMER_REJECT"


class ResolutionOutcome(str, Enum):
    CONSUMER_ACCEPTED = "CONSUMER_ACCEPTED"
    CONSUMER_REJECTED = "CONSUMER_REJECTED"
    AUTO_UNANSWERED = "AUTO_UNANSWERED"
    MEDIATION_AGREEMENT = "MEDIATION_AGREEMENT"
    MEDIATION_NO_AGREEMENT = "MEDIATION_NO_AGREEMENT"
    ARBITRATION_ADVERSE = "ARBITRATION_ADVERSE"
    ARBITRATION_NO_FAULT = "ARBITRATION_NO_FAULT"


class MediationCaseStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    DECLINED_EXPIRED = "DECLINED_EXPIRED"
    SCHEDULED = "SCHEDULED"
    CONCLUDED_AGREEMENT = "CONCLUDED_AGREEMENT"
    CONCLUDED_NO_AGREEMENT = "CONCLUDED_NO_AGREEMENT"


class MediationParty(str, Enum):
    BUSINESS = "BUSINESS"
    CONSUMER = "CONSUMER"


class MediationPartyResponse(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class MediationOutcome(str, Enum):
    AGREEMENT = "AGREEMENT"
    NO_AGREEMENT = "NO_AGREEMENT"


class ArbitrationCaseStatus(str, Enum):
    FILED = "FILED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    DECIDED = "DECIDED"


class ArbitrationOutcome(str, Enum):
    ADVERSE_TO_BUSINESS = "ADVERSE_TO_BUSINESS"
    NO_FAULT = "NO_FAULT"


class RatingVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    PUBLISHED = "PUBLISHED"


class Grade(str, Enum):
    A_PLUS = "A_PLUS"
    A = "A"
    A_MINUS = "A_MINUS"
    B_PLUS = "B_PLUS"
    B = "B"
    B_MINUS = "B_MINUS"
    C_PLUS = "C_PLUS"
    C = "C"
    C_MINUS = "C_MINUS"
    D_PLUS = "D_PLUS"
    D = "D"
    F = "F"


class RatingDisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_APPEAL_REVIEW = "UNDER_APPEAL_REVIEW"
    UPHELD = "UPHELD"
    OVERRULED = "OVERRULED"


class AppealDecision(str, Enum):
    UPHELD = "UPHELD"
    OVERRULED = "OVERRULED"


class AdvertisingReviewStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    CLEARED = "CLEARED"
    REFERRED_TO_REGULATOR = "REFERRED_TO_REGULATOR"


class AdvertisingReviewOutcome(str, Enum):
    CLEARED = "CLEARED"
    SUBSTANTIATED_DECEPTIVE = "SUBSTANTIATED_DECEPTIVE"


class ScamReportStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PUBLISHED = "PUBLISHED"


# Complaint status partitions (PRD §3.4 counter definitions / §3.6 input sets)
OPEN_COMPLAINT_STATES = (
    "RECEIVED", "FORWARDED", "RESPONSE_RECEIVED", "CONSUMER_REBUTTED",
    "MEDIATION_OFFERED", "IN_MEDIATION", "UNRESOLVED", "MEDIATION_FAILED",
    "IN_ARBITRATION",
)
CLOSED_COMPLAINT_STATES = (
    "RESOLVED", "UNANSWERED", "MEDIATION_RESOLVED", "ARBITRATED",
)
OUTCOME_COMPLAINT_STATES = (
    "RESOLVED", "UNANSWERED", "UNRESOLVED", "MEDIATION_RESOLVED",
    "MEDIATION_FAILED", "ARBITRATED",
)
PENDING_COMPLAINT_STATES = (
    "RECEIVED", "FORWARDED", "RESPONSE_RECEIVED", "CONSUMER_REBUTTED",
    "MEDIATION_OFFERED", "IN_MEDIATION", "IN_ARBITRATION",
)


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5 common properties on every resource)
# ---------------------------------------------------------------------------
class Bureau(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    territory_state_codes: List[str]
    local_dues_fee_cents: int
    dues_collected_cents: int
    ops_day_index: int


class Consumer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    email: str
    home_state_code: str
    complaints_filed_count: int


class Business(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    home_state_code: str
    employee_count: int
    founded_on: str
    bureau_id: str
    size_tier: str
    accreditation_status: str
    advertising_compliance_status: str
    suspension_count_24m: int
    last_suspension_at: Optional[str]
    complaints_received_36m: int
    complaints_unanswered_36m: int
    complaints_unresolved_36m: int
    complaints_open_count: int
    complaints_closed_count: int
    published_scam_count_12m: int
    current_published_score: Optional[int]
    current_published_grade: Optional[str]
    current_provisional_score: Optional[int]
    current_provisional_grade: Optional[str]


class AccreditationApplication(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    business_id: str
    billing_plan: str
    license_number: str
    status: str
    reapplication_count: int
    submitted_at: Optional[str]
    decided_at: Optional[str]
    denial_reason: Optional[str]
    advertising_practices_result: Optional[str]
    complaint_history_result: Optional[str]
    licensing_result: Optional[str]
    dues_invoice_id: Optional[str]


class DuesInvoiceInstallment(TypedDict):
    installment: int
    amount_cents: int


class DuesInvoice(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    business_id: str
    application_id: str
    billing_plan: str
    size_tier_at_issue: str
    base_amount_cents: int
    local_fee_cents: int
    amount_due_cents: int
    installments: List[DuesInvoiceInstallment]
    paid_cents: int
    refunded_cents: int
    balance_cents: int
    status: str
    issued_at: str
    due_date: str
    voided_at: Optional[str]


class ComplaintResponse(TypedDict):
    kind: str
    body: str
    received_at: str
    on_time: bool


class Complaint(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    consumer_id: str
    business_id: str
    category: str
    description: str
    status: str
    filed_at: str
    forwarded_at: Optional[str]
    response_deadline_at: Optional[str]
    last_unresolved_at: Optional[str]
    resolution_outcome: Optional[str]
    rebuttal_count: int
    reopen_count: int
    closed_at: Optional[str]
    responses: List[ComplaintResponse]


class MediationCase(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    complaint_id: str
    status: str
    offered_at: str
    offer_deadline_at: str
    business_response: str
    consumer_response: str
    mediator_id: Optional[str]
    session_start_at: Optional[str]
    session_end_at: Optional[str]


class ArbitrationCase(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    complaint_id: str
    source_mediation_case_id: str
    status: str
    hearing_room_id: Optional[str]
    hearing_start_at: Optional[str]
    hearing_end_at: Optional[str]
    outcome: Optional[str]
    decided_at: Optional[str]


class RatingSnapshot(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    business_id: str
    variant: str
    volume_deduction: int
    unanswered_deduction: int
    unresolved_deduction: int
    arbitration_deduction: int
    age_deduction: int
    advertising_deduction: int
    scam_deduction: int
    pending_deduction: int
    total_deductions: int
    score: int
    grade: str
    window_start_at: str
    computed_at: str
    published_at: Optional[str]
    excluded_complaint_id: Optional[str]
    superseded_by_id: Optional[str]


class RatingDispute(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    business_id: str
    snapshot_id: str
    reason: str
    disputed_complaint_id: Optional[str]
    status: str
    filed_at: str


class AdvertisingReview(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    business_id: str
    claim_description: str
    status: str
    regulator_name: Optional[str]
    opened_at: str
    concluded_at: Optional[str]
    referred_at: Optional[str]


class ScamReport(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    consumer_id: str
    business_id: str
    description: str
    incident_date: str
    status: str
    published_at: Optional[str]


class ScamPatternRow(TypedDict):
    business_id: str
    legal_name: str
    published_report_count_12m: int
    pattern_flag: bool
