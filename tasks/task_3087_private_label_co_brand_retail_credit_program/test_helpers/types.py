"""Domain types for the private-label retail credit program API.

Entity shapes, status enumerations and the seven-role enumeration. Every
entity in this program carries the full common property set — ``id``,
``created_at``, ``updated_at`` and ``version`` — so no TypedDict here omits
``updated_at`` or ``version``.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    RETAIL_PARTNER_ANALYST = "RetailPartnerAnalyst"
    UNDERWRITER = "Underwriter"
    CARDHOLDER_SERVICE = "CardholderService"
    CARDHOLDER = "Cardholder"
    APPLICANT = "Applicant"
    CO_BRAND_ISSUER = "CoBrandIssuer"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDING = "OFFBOARDING"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    NEGOTIATION = "NEGOTIATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RENEWAL_NEGOTIATION = "RENEWAL_NEGOTIATION"
    WINDING_DOWN = "WINDING_DOWN"
    CLOSED = "CLOSED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    CHARGED_OFF = "CHARGED_OFF"
    PAID_OFF = "PAID_OFF"
    TRANSFERRED = "TRANSFERRED"


class ApplicationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class SourceChannel(str, Enum):
    IN_STORE = "IN_STORE"
    DIGITAL = "DIGITAL"
    PRESCREENED = "PRESCREENED"


class TransactionStatus(str, Enum):
    POSTED = "POSTED"
    DISPUTED = "DISPUTED"


class TransactionChannel(str, Enum):
    IN_STORE = "IN_STORE"
    DIGITAL = "DIGITAL"


class PromoPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    EXPIRED = "EXPIRED"


class SettlementMethod(str, Enum):
    FORWARD_LOOKING = "FORWARD_LOOKING"
    AS_CHARGED = "AS_CHARGED"


class ReconciliationMethod(str, Enum):
    PROJECTED = "PROJECTED"
    AS_CHARGED = "AS_CHARGED"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"


class DisputeCaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_FAVOR_CARDHOLDER = "RESOLVED_FAVOR_CARDHOLDER"
    RESOLVED_FAVOR_MERCHANT = "RESOLVED_FAVOR_MERCHANT"
    CLOSED = "CLOSED"


class DisputeReason(str, Enum):
    FRAUD = "FRAUD"
    GOODS_NOT_RECEIVED = "GOODS_NOT_RECEIVED"
    UNAUTHORIZED = "UNAUTHORIZED"
    DUPLICATE_CHARGE = "DUPLICATE_CHARGE"
    SERVICE_NOT_RENDERED = "SERVICE_NOT_RENDERED"


class ResolutionOutcome(str, Enum):
    CARDHOLDER = "CARDHOLDER"
    MERCHANT = "MERCHANT"


class PostingReason(str, Enum):
    PURCHASE_EARN = "PURCHASE_EARN"
    PROMO_BONUS = "PROMO_BONUS"
    DISPUTE_CLAWBACK = "DISPUTE_CLAWBACK"


class PostedStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class BalanceBucket(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    PROMO_PRINCIPAL = "PROMO_PRINCIPAL"


class TransferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    AGREEMENT_REACHED = "AGREEMENT_REACHED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class BuyerRole(str, Enum):
    RETAILER = "RETAILER"
    ISSUER = "ISSUER"


class RetailPartner(TypedDict):
    id: str
    retailer_name: str
    partner_status: str
    loyalty_program_code: str
    loyalty_link_enabled: bool
    partner_portfolio_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class ProgramAgreement(TypedDict):
    id: str
    partner_id: str
    agreement_status: str
    revenue_share_rate: float
    promo_subsidy_rate: float
    promo_term_months: int
    minimum_charge_cents: int
    settlement_terms_days: int
    dispute_grace_days: int
    renewal_notice_days: int
    purchase_right_rate: float
    created_at: str
    updated_at: str
    version: int


class CreditProgram(TypedDict):
    id: str
    partner_id: str
    agreement_id: str
    program_status: str
    supersedes_program_id: Optional[str]
    outstanding_receivable_cents: int
    free_look_exposure_cents: int
    program_profitability_cents: int
    cycle_day: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    program_id: str
    cardholder_ref: str
    account_status: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    linked_loyalty_balance: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    program_id: str
    source_channel: str
    requested_credit_limit_cents: int
    prescreen_reference: Optional[str]
    application_status: str
    decision_code: Optional[str]
    approved_credit_limit_cents: Optional[int]
    instant_decision_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    account_id: str
    merchant_name: str
    amount_cents: int
    transaction_channel: str
    transaction_status: str
    promo_requested: bool
    promo_term_months: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PromoPlan(TypedDict):
    id: str
    program_id: str
    account_id: str
    transaction_id: str
    promo_term_months: int
    promo_principal_cents: int
    qualifying_flag: bool
    subsidy_at_application_cents: int
    subsidy_at_risk_cents: int
    net_subsidy_cents: Optional[int]
    promo_start_at: str
    promo_expires_at: str
    plan_status: str
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict):
    id: str
    agreement_id: str
    period_start: str
    period_end: str
    settlement_method: str
    reconciliation_method: str
    transaction_count: int
    gross_subsidy_cents: int
    net_subsidy_cents: int
    retailer_liability_cents: int
    issuer_subsidy_cents: int
    variance_cents: int
    batch_status: str
    created_at: str
    updated_at: str
    version: int


class DisputeCase(TypedDict):
    id: str
    transaction_id: str
    account_id: str
    dispute_reason: str
    case_status: str
    resolution_outcome: Optional[str]
    resolved_at: Optional[str]
    chargeback_amount_cents: Optional[int]
    program_exposure_delta_cents: int
    servicing_brand_name: str
    created_at: str
    updated_at: str
    version: int


class BenefitPosting(TypedDict):
    id: str
    account_id: str
    transaction_id: str
    posting_reason: str
    points_amount: int
    posts_to_retailer_loyalty: bool
    loyalty_program_code: Optional[str]
    posted_status: str
    posted_at: str
    created_at: str
    updated_at: str
    version: int


class ScheduledBalance(TypedDict):
    id: str
    account_id: str
    principal_balance_cents: int
    balance_bucket: str
    recorded_at: str
    created_at: str
    updated_at: str
    version: int


class WindDownTransfer(TypedDict):
    id: str
    program_id: str
    buyer_role: str
    transfer_status: str
    portfolio_book_value_cents: int
    purchase_right_rate: float
    purchase_price_cents: int
    accepted_by_role: Optional[str]
    transfer_executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int