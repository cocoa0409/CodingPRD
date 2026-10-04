"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    FRANCHISEE_OWNER = "FranchiseeOwner"
    BROKER_OF_RECORD = "BrokerOfRecord"
    MANAGING_BROKER = "ManagingBroker"
    AGENT = "Agent"
    TRUST_ACCOUNTANT = "TrustAccountant"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    PLATFORM_ADMIN = "PlatformAdmin"


class OfficeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class FeeScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class AgentStatus(str, Enum):
    PENDING_ONBOARDING = "PENDING_ONBOARDING"
    ACTIVE = "ACTIVE"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    TERMINATED = "TERMINATED"


class FeeAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class TransactionStatus(str, Enum):
    LISTED = "LISTED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    PENDING_CLOSE = "PENDING_CLOSE"
    CLOSED = "CLOSED"
    FELL_THROUGH = "FELL_THROUGH"
    RELISTED = "RELISTED"


class CdaStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ClosingLineType(str, Enum):
    GCI = "GCI"
    REFERRAL_FEE = "REFERRAL_FEE"
    AGENT_RETENTION = "AGENT_RETENTION"
    OFFICE_SPLIT = "OFFICE_SPLIT"
    OVERHEAD_SHARE = "OVERHEAD_SHARE"
    ADVANCE_RECOVERY = "ADVANCE_RECOVERY"


class ClosingLineVariant(str, Enum):
    STANDARD = "STANDARD"
    FORMER_AGENT = "FORMER_AGENT"


class ClosingLineStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    VOIDED = "VOIDED"


class InvoiceOrigin(str, Enum):
    AUTO_RUN = "AUTO_RUN"
    DEPARTURE = "DEPARTURE"
    MANUAL = "MANUAL"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    COLLECTIONS = "COLLECTIONS"
    WRITTEN_OFF = "WRITTEN_OFF"
    CANCELLED = "CANCELLED"


class InvoiceLineKind(str, Enum):
    DESK_FEE = "DESK_FEE"
    OVERHEAD_SHARE = "OVERHEAD_SHARE"
    TECH_SUBSCRIPTION = "TECH_SUBSCRIPTION"
    MARKETING = "MARKETING"
    PRORATED_DESK_FEE = "PRORATED_DESK_FEE"
    ADVANCE_RECOVERY = "ADVANCE_RECOVERY"


class EntryKind(str, Enum):
    GCI_RECEIPT = "GCI_RECEIPT"
    AGENT_DISBURSEMENT = "AGENT_DISBURSEMENT"
    OFFICE_FEE_ACCRUAL = "OFFICE_FEE_ACCRUAL"
    REFERRAL_PAYOUT = "REFERRAL_PAYOUT"
    ADVANCE = "ADVANCE"
    ADVANCE_RETURN = "ADVANCE_RETURN"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    DEPARTURE_HOLD = "DEPARTURE_HOLD"
    DEPARTURE_RELEASE = "DEPARTURE_RELEASE"


class EntryStatus(str, Enum):
    ESCROW_HELD = "ESCROW_HELD"
    AGENT_PAYABLE = "AGENT_PAYABLE"
    OFFICE_FEE_ACCRUED = "OFFICE_FEE_ACCRUED"
    REFERRAL_PAYABLE = "REFERRAL_PAYABLE"
    DEPARTURE_HOLD = "DEPARTURE_HOLD"
    DISBURSED = "DISBURSED"
    RECONCILED = "RECONCILED"
    REVERSED = "REVERSED"


class ReferralStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class ReportVariant(str, Enum):
    CHURN = "CHURN"
    COHORT = "COHORT"


class ReportStatus(str, Enum):
    COMPUTED = "COMPUTED"
    ARCHIVED = "ARCHIVED"


# --- Entity TypedDicts (all entities carry the common fields of PRD §2.5) ---


class Office(TypedDict, total=False):
    id: str
    office_name: str
    market_code: str
    status: str
    recruiting_target_agents: int
    active_agent_count: int
    trust_balance_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict, total=False):
    id: str
    schedule_name: str
    desk_fee_cents: int
    overhead_share_bps: int
    retention_bps: int
    referral_fee_bps: int
    tech_subscription_monthly_cents: int
    marketing_monthly_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    office_id: str
    full_name: str
    email: str
    license_number: str
    status: str
    onboarded_at: Optional[str]
    termination_requested_at: Optional[str]
    terminated_at: Optional[str]
    supervision_cadence_days: int
    unearned_advance_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class FeeAssignment(TypedDict, total=False):
    id: str
    agent_id: str
    fee_schedule_id: str
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    office_id: str
    listing_reference: str
    buyer_name: str
    offer_price_cents: int
    offer_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict, total=False):
    id: str
    office_id: str
    listing_agent_id: str
    selling_agent_id: str
    offer_id: str
    sale_price_cents: int
    gross_commission_cents: int
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Cda(TypedDict, total=False):
    id: str
    transaction_id: str
    authorizing_broker_id: str
    review_ladder: List[str]
    current_rung: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClosingStatementLine(TypedDict, total=False):
    id: str
    transaction_id: str
    line_type: str
    agent_id: Optional[str]
    amount_cents: int
    applied_invoice_line_id: Optional[str]
    variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    office_id: str
    agent_id: str
    billing_month: str
    origin: str
    amount_due_cents: int
    due_date: str
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    id: str
    invoice_id: str
    line_kind: str
    period_label: str
    amount_cents: int
    applied_at_closing_cents: int
    created_at: str
    updated_at: str
    version: int


class CommissionEntry(TypedDict, total=False):
    id: str
    office_id: str
    transaction_id: Optional[str]
    entry_kind: str
    amount_cents: int
    entry_month: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReferralAgreement(TypedDict, total=False):
    id: str
    referring_office_id: str
    receiving_office_id: str
    agent_id: str
    referral_fee_bps: int
    status: str
    replaces_agreement_id: Optional[str]
    fulfilled_transaction_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgentRetentionReport(TypedDict, total=False):
    id: str
    office_id: str
    period_month: str
    headcount_start: int
    headcount_end: int
    retention_bps: int
    churned_agent_count: int
    report_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int
