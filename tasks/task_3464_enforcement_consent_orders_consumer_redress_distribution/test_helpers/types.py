"""Domain types: entity TypedDicts, status enums, role enum.

PRD reference: section 2.4 (common resource properties), section 2.1 (roles),
section 3 (per-entity field vocabularies). Every resource in this system
carries id, created_at, updated_at, and version (PRD section 2.4: "No
resource in this system is exempt from this convention").
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STAFF_ATTORNEY = "StaffAttorney"
    COMMISSIONER = "Commissioner"
    COMPLIANCE_MONITOR = "ComplianceMonitor"
    FUND_ADMINISTRATOR = "FundAdministrator"
    DISBURSEMENT_OFFICER = "DisbursementOfficer"
    COMPANY_REPRESENTATIVE = "CompanyRepresentative"
    CLAIMANT = "Claimant"


class RiskTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class InvestigationOrigin(str, Enum):
    COMPLAINT = "COMPLAINT"
    REFERRAL = "REFERRAL"
    MARKET_MONITORING = "MARKET_MONITORING"


class InvestigationStatus(str, Enum):
    INTAKE = "INTAKE"
    PRELIMINARY_REVIEW = "PRELIMINARY_REVIEW"
    EVIDENCE_GATHERING = "EVIDENCE_GATHERING"
    NEGOTIATING = "NEGOTIATING"
    SETTLED = "SETTLED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    CLOSED_ORDER_ENTERED = "CLOSED_ORDER_ENTERED"


class CidStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    QUASH_PETITIONED = "QUASH_PETITIONED"
    ENFORCED = "ENFORCED"
    RESPONDED = "RESPONDED"
    WITHDRAWN = "WITHDRAWN"


class ConsentOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_PUBLIC_COMMENT = "IN_PUBLIC_COMMENT"
    FINAL = "FINAL"
    IN_MONITORING = "IN_MONITORING"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class CommentPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class ComplianceReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"


class PenaltySeverity(str, Enum):
    STANDARD = "STANDARD"
    AGGRAVATED = "AGGRAVATED"
    EGREGIOUS = "EGREGIOUS"


class ViolationPenaltyStatus(str, Enum):
    ASSESSED_PROVISIONAL = "ASSESSED_PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class CollectionStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    PARTIALLY_COLLECTED = "PARTIALLY_COLLECTED"
    SATISFIED = "SATISFIED"


class SuspensionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REINSTATED = "REINSTATED"


class PaymentKind(str, Enum):
    COLLECTION = "COLLECTION"
    REVERSAL = "REVERSAL"


class RedressFundStatus(str, Enum):
    ACCUMULATING = "ACCUMULATING"
    OPEN_FOR_CLAIMS = "OPEN_FOR_CLAIMS"
    CLAIMS_CLOSED = "CLAIMS_CLOSED"
    DISBURSING = "DISBURSING"
    RESIDUAL_DISPOSITION = "RESIDUAL_DISPOSITION"
    CLOSED = "CLOSED"


class ResidualDisposition(str, Enum):
    NONE = "NONE"
    CY_PRES = "CY_PRES"
    TREASURY_ESCHEAT = "TREASURY_ESCHEAT"


class IdentifiedFrom(str, Enum):
    COMPANY_RECORDS = "COMPANY_RECORDS"
    CLAIMS_PROCESS = "CLAIMS_PROCESS"


class ClaimantStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    NOTIFIED = "NOTIFIED"
    CLAIMED = "CLAIMED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    DENIED = "DENIED"


class RefundCheckStatus(str, Enum):
    ISSUED = "ISSUED"
    CASHED = "CASHED"
    STALE = "STALE"
    VOIDED = "VOIDED"


class SubjectCompany(TypedDict):
    id: str
    legal_name: str
    complaint_count_90d: int
    risk_tier: str
    created_at: str
    updated_at: str
    version: int


class Investigation(TypedDict):
    id: str
    subject_company_id: str
    origin: str
    summary: str
    opened_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CivilInvestigativeDemand(TypedDict):
    id: str
    investigation_id: str
    subject_matter: str
    response_due_date: str
    response_document_ref: Optional[str]
    responded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentOrder(TypedDict):
    id: str
    investigation_id: str
    subject_company_id: str
    negotiating_attorney_user_id: str
    monetary_relief_cents: int
    max_penalty_cents: int
    reporting_frequency_months: int
    monitoring_term_years: int
    conduct_prohibitions: List[str]
    proposal_round: int
    monitoring_started_at: Optional[str]
    monitoring_ends_at: Optional[str]
    finalized_at: Optional[str]
    finalized_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PublicCommentPeriod(TypedDict):
    id: str
    consent_order_id: str
    round: int
    opened_at: str
    closes_at: str
    comments: List[Dict[str, Any]]
    comment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict):
    id: str
    consent_order_id: str
    submitted_by_company_id: str
    period_start: str
    period_end: str
    report_document_ref: str
    status: str
    deficiency_notes: Optional[str]
    resubmission_count: int
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ViolationPenalty(TypedDict):
    id: str
    consent_order_id: str
    severity: str
    detected_on: str
    description: str
    assessed_by_user_id: str
    provisional_days: int
    provisional_amount_cents: int
    cured_on: Optional[str]
    final_days: Optional[int]
    final_amount_cents: Optional[int]
    confirmed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MonetaryJudgment(TypedDict):
    id: str
    consent_order_id: str
    amount_cents: int
    collected_cents: int
    outstanding_cents: int
    collection_status: str
    suspension_status: str
    sworn_total_assets_cents: Optional[int]
    asset_trace_log: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class RedressFund(TypedDict):
    id: str
    judgment_id: str
    consent_order_id: str
    total_collected_cents: int
    admin_reserve_cents: int
    distributable_pool_cents: int
    allocated_cents: int
    disbursed_cents: int
    available_cents: int
    residual_cents: int
    residual_disposition: str
    residual_recipient_name: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claimant(TypedDict):
    id: str
    redress_fund_id: str
    full_name: str
    email: str
    identified_from: str
    notified_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    claimant_id: str
    redress_fund_id: str
    documented_loss_cents: int
    eligible_loss_cents: Optional[int]
    provisional_award_cents: Optional[int]
    final_award_cents: Optional[int]
    approved_by_user_id: Optional[str]
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundCheck(TypedDict):
    id: str
    claim_id: str
    redress_fund_id: str
    amount_cents: int
    issued_at: str
    stale_after: str
    reissue_deadline: str
    original_check_id: Optional[str]
    fraud_warning_text: str
    cashed_at: Optional[str]
    voided_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
