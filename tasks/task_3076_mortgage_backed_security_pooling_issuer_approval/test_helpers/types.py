"""Domain types: entity TypedDicts, status enums, role enum.

All entity models mirror the PRD's resource surface. Primary resources carry
id, created_at, updated_at and version; AccountTransaction is the single
append-only ledger entity and carries only id and created_at.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class IssuerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"
    DEFAULTED = "DEFAULTED"
    EXTINGUISHED = "EXTINGUISHED"


class EngagementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class PoolType(str, Enum):
    SINGLE_FAMILY = "SINGLE_FAMILY"
    MANUFACTURED_HOME = "MANUFACTURED_HOME"
    MULTIFAMILY = "MULTIFAMILY"


class PoolStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSEMBLED = "ASSEMBLED"
    CERTIFIED = "CERTIFIED"
    LIVE = "LIVE"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    TERMINATED = "TERMINATED"


class LoanStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQ_30 = "DELINQ_30"
    DELINQ_60 = "DELINQ_60"
    DELINQ_90_PLUS = "DELINQ_90_PLUS"
    FORECLOSURE = "FORECLOSURE"
    PAID_OFF = "PAID_OFF"


class GovernmentInsurance(str, Enum):
    FHA = "FHA"
    VA = "VA"
    USDA = "USDA"
    PIH = "PIH"


class AccountType(str, Enum):
    P_AND_I = "P_AND_I"
    T_AND_I = "T_AND_I"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class TransactionDirection(str, Enum):
    DEPOSIT = "DEPOSIT"
    DISBURSEMENT = "DISBURSEMENT"


class TransactionComponent(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    INTEREST = "INTEREST"
    TAX = "TAX"
    INSURANCE = "INSURANCE"
    ESCROW = "ESCROW"


class CertificationDecision(str, Enum):
    CERTIFIED = "CERTIFIED"
    EXCEPTION = "EXCEPTION"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PaymentStatus(str, Enum):
    DUE = "DUE"
    PAID = "PAID"
    ADVANCED = "ADVANCED"


class FundingSource(str, Enum):
    CUSTODIAL = "CUSTODIAL"
    ADVANCE = "ADVANCE"


class AdvanceStatus(str, Enum):
    OPEN = "OPEN"
    REIMBURSED = "REIMBURSED"
    WRITTEN_OFF = "WRITTEN_OFF"


class BreachStatus(str, Enum):
    OPEN = "OPEN"
    MITIGATING = "MITIGATING"
    CLOSED = "CLOSED"


class PlanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class TransferStatus(str, Enum):
    INITIATED = "INITIATED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"


class UserRole(str, Enum):
    APPLICANT_OFFICER = "ApplicantOfficer"
    AGENCY_REVIEWER = "AgencyReviewer"
    ISSUER_OFFICER = "IssuerOfficer"
    DOCUMENT_CUSTODIAN = "DocumentCustodian"
    PLATFORM_ADMIN = "PlatformAdmin"


class IssuerApplication(TypedDict, total=False):
    id: str
    legal_name: str
    net_worth_cents: int
    liquid_assets_cents: int
    unused_credit_lines_cents: int
    origination_experience_months: int
    branch_count: int
    annual_origination_volume_cents: int
    net_worth_requirement_cents: int
    status: str
    approved_issuer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Issuer(TypedDict, total=False):
    id: str
    application_id: str
    legal_name: str
    net_worth_cents: int
    liquid_assets_cents: int
    unused_credit_lines_cents: int
    advance_obligation_cents: int
    liquidity_ratio_excluding_credit_bps: Optional[int]
    liquidity_ratio_including_credit_bps: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DocumentCustodian(TypedDict, total=False):
    id: str
    firm_name: str
    created_at: str
    updated_at: str
    version: int


class CustodianEngagement(TypedDict, total=False):
    id: str
    custodian_id: str
    issuer_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Pool(TypedDict, total=False):
    id: str
    issuer_id: str
    custodian_id: str
    pool_type: str
    term_months: int
    note_rate_bps: int
    aggregate_principal_cents: int
    delinquency_rate_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    pool_id: str
    principal_balance_cents: int
    note_rate_bps: int
    government_insurance: str
    escrow_monthly_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustodialAccount(TypedDict, total=False):
    id: str
    issuer_id: str
    account_type: str
    principal_balance_cents: int
    interest_balance_cents: int
    tax_balance_cents: int
    insurance_balance_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger: carries ONLY id + created_at (no updated_at, no version).
class AccountTransaction(TypedDict, total=False):
    id: str
    account_id: str
    direction: str
    component: str
    amount_cents: int
    loan_id: Optional[str]
    tax_split_cents: Optional[int]
    insurance_split_cents: Optional[int]
    created_at: str


class LoanFileCertification(TypedDict, total=False):
    id: str
    pool_id: str
    custodian_id: str
    decision: str
    exception_loan_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class InvestorReport(TypedDict, total=False):
    id: str
    pool_id: str
    period_month: str
    scheduled_payment_cents: int
    actual_collected_cents: int
    advance_required_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PassThroughPayment(TypedDict, total=False):
    id: str
    report_id: str
    amount_cents: int
    funding_source: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LiquidityAdvance(TypedDict, total=False):
    id: str
    issuer_id: str
    payment_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DelinquencyBreach(TypedDict, total=False):
    id: str
    issuer_id: str
    pool_id: str
    delinquency_rate_bps_at_breach: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrectiveActionPlan(TypedDict, total=False):
    id: str
    breach_id: str
    plan_summary: str
    target_cure_month: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PortfolioTransfer(TypedDict, total=False):
    id: str
    defaulted_issuer_id: str
    successor_issuer_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
