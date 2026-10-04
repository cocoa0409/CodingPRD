"""Domain types: entity TypedDicts, status enums, role enum for the GSE Loan Delivery API."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class SellerStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ServicerStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class QcRating(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    UNSATISFACTORY = "UNSATISFACTORY"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class LlpaMatrixStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class LoanStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDERWRITTEN = "UNDERWRITTEN"
    DELIVERED = "DELIVERED"
    PURCHASED = "PURCHASED"
    REJECTED = "REJECTED"
    REPURCHASED = "REPURCHASED"


class AuStatus(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    RECOMMEND_APPROVE = "RECOMMEND_APPROVE"
    RECOMMEND_REFER = "RECOMMEND_REFER"
    INELIGIBLE = "INELIGIBLE"


class ReliefTier(str, Enum):
    NONE = "NONE"
    PAYMENT_HISTORY_36 = "PAYMENT_HISTORY_36"
    INDEPENDENT_VALIDATION = "INDEPENDENT_VALIDATION"


class Occupancy(str, Enum):
    PRIMARY_RESIDENCE = "PRIMARY_RESIDENCE"
    SECOND_HOME = "SECOND_HOME"
    INVESTMENT = "INVESTMENT"


class ProductType(str, Enum):
    FIXED_30 = "FIXED_30"
    FIXED_15 = "FIXED_15"
    ARM_5_1 = "ARM_5_1"


class CaseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"
    FINALIZED = "FINALIZED"


class Recommendation(str, Enum):
    PENDING = "PENDING"
    APPROVE_ELIGIBLE = "APPROVE_ELIGIBLE"
    REFER_WITH_CAUTION = "REFER_WITH_CAUTION"


class FinalOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class ServiceType(str, Enum):
    INCOME = "INCOME"
    ASSET = "ASSET"
    EMPLOYMENT = "EMPLOYMENT"


class ReportResult(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    NOT_VALIDATED = "NOT_VALIDATED"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    ISSUED = "ISSUED"
    CANCELLED = "CANCELLED"


class PaymentOutcome(str, Enum):
    ON_TIME = "ON_TIME"
    LATE = "LATE"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"


class FindingStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    REPURCHASE_ISSUED = "REPURCHASE_ISSUED"
    APPEALED = "APPEALED"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    REMEDIATED = "REMEDIATED"


class DefectCategory(str, Enum):
    INCOME_MISREP = "INCOME_MISREP"
    ASSET_MISREP = "ASSET_MISREP"
    EMPLOYMENT_MISREP = "EMPLOYMENT_MISREP"
    COLLATERAL = "COLLATERAL"
    ELIGIBILITY = "ELIGIBILITY"
    OTHER = "OTHER"


class Severity(str, Enum):
    SIGNIFICANT = "SIGNIFICANT"
    MODERATE = "MODERATE"
    MINOR = "MINOR"


class DemandStatus(str, Enum):
    ISSUED = "ISSUED"
    APPEALED = "APPEALED"
    UPHELD = "UPHELD"
    WITHDRAWN = "WITHDRAWN"
    SETTLED = "SETTLED"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OversightStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SamplingMethod(str, Enum):
    RANDOM = "RANDOM"
    TARGETED = "TARGETED"
    DISCRETIONARY = "DISCRETIONARY"


class UserRole(str, Enum):
    GSE_ADMIN = "GseAdmin"
    SELLER_OFFICER = "SellerOfficer"
    UNDERWRITER = "Underwriter"
    GSE_UNDERWRITING_ENGINE = "GseUnderwritingEngine"
    QC_AUDITOR = "QcAuditor"
    SERVICER_OFFICER = "ServicerOfficer"


class Seller(TypedDict, total=False):
    id: str
    legal_name: str
    seller_number: str
    net_worth_cents: int
    qc_defect_rate_bps: int
    status: str
    approval_cycle: int
    probation_relief_enabled: bool
    created_at: str
    updated_at: str
    version: int


class Servicer(TypedDict, total=False):
    id: str
    legal_name: str
    servicer_number: str
    net_worth_cents: int
    qc_rating: str
    status: str
    oversight_score: int
    created_at: str
    updated_at: str
    version: int


class MasterAgreement(TypedDict, total=False):
    id: str
    seller_id: str
    servicer_id: str
    effective_date: str
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LlpaMatrix(TypedDict, total=False):
    id: str
    effective_from: str
    effective_until: str
    rows: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    seller_id: str
    servicer_id: str
    agreement_id: str
    loan_number: str
    borrower_name: str
    unpaid_principal_balance_cents: int
    appraised_value_cents: int
    credit_score: int
    occupancy: str
    product_type: str
    ltv_bp: int
    au_status: str
    status: str
    relief_tier: str
    consecutive_on_time_payments: int
    independent_validation_complete: bool
    pool_id: Optional[str]
    delivery_price_cents: Optional[int]
    applied_llpa_bps: Optional[int]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnderwritingCase(TypedDict, total=False):
    id: str
    loan_id: str
    seller_id: str
    submission_round: int
    case_status: str
    recommendation: str
    final_outcome: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only; carries ONLY id + created_at
class ValidationReport(TypedDict, total=False):
    id: str
    case_id: str
    round: int
    service_type: str
    result: str
    provider_reference: str
    created_at: str


class Pool(TypedDict, total=False):
    id: str
    seller_id: str
    agreement_id: str
    pool_number: str
    issue_date: str
    target_balance_cents: int
    current_balance_cents: int
    loan_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only; carries ONLY id + created_at
class PaymentEvent(TypedDict, total=False):
    id: str
    loan_id: str
    due_date: str
    paid_on_time: bool
    amount_cents: int
    outcome: str
    created_at: str


class QcAudit(TypedDict, total=False):
    id: str
    seller_id: str
    sampling_method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QcFinding(TypedDict, total=False):
    id: str
    audit_id: str
    loan_id: str
    defect_category: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RepurchaseDemand(TypedDict, total=False):
    id: str
    finding_id: str
    loan_id: str
    amount_cents: int
    status: str
    appeal_deadline: str
    appeal_rounds_used: int
    created_at: str
    updated_at: str
    version: int


class ServicingTransfer(TypedDict, total=False):
    id: str
    loan_id: str
    from_servicer_id: str
    to_servicer_id: str
    effective_date: str
    requester_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SubservicerOversight(TypedDict, total=False):
    id: str
    servicer_id: str
    subservicer_id: str
    oversight_period_start: str
    oversight_period_end: str
    findings_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Pipeline(TypedDict, total=False):
    id: str
    seller_id: str
    projected_value_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only; carries ONLY id + created_at
class LlpaUpdateEvent(TypedDict, total=False):
    id: str
    pipeline_id: str
    old_matrix_id: str
    new_matrix_id: str
    projected_value_before_cents: int
    projected_value_after_cents: int
    delta_cents: int
    impacted_loan_count: int
    created_at: str
