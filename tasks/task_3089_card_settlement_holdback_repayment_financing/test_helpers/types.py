"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the common server-minted fields (id, created_at,
updated_at, version) per PRD Section 2.4.
"""
from enum import Enum
from typing import Optional, TypedDict


class MerchantStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    SWEPT = "SWEPT"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    REUNDERWRITING = "REUNDERWRITING"
    WITHDRAWN = "WITHDRAWN"


class GuarantorStatus(str, Enum):
    LINKED = "LINKED"
    ACTIVE = "ACTIVE"
    ENFORCED = "ENFORCED"
    RELEASED = "RELEASED"


class LoanStatus(str, Enum):
    PENDING_DISCLOSURE = "PENDING_DISCLOSURE"
    PENDING_ACK = "PENDING_ACK"
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    REPAID = "REPAID"
    CHARGED_OFF = "CHARGED_OFF"


class DisclosureStatus(str, Enum):
    GENERATED = "GENERATED"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class SweepStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class CatchUpStatus(str, Enum):
    INITIATED = "INITIATED"
    APPLIED = "APPLIED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class EnforcementStatus(str, Enum):
    DRAFT = "DRAFT"
    DEMANDED = "DEMANDED"
    ESCALATED = "ESCALATED"
    DRAWN = "DRAWN"
    RELEASED = "RELEASED"


class BankStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SaleStatus(str, Enum):
    QUOTED = "QUOTED"
    COMMITTED = "COMMITTED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class SignalStatus(str, Enum):
    DETECTED = "DETECTED"
    CONFIRMED = "CONFIRMED"
    CLEARED = "CLEARED"
    DISMISSED = "DISMISSED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    UNDERWRITER = "Underwriter"
    SERVICER_AGENT = "ServicerAgent"
    MERCHANT_OWNER = "MerchantOwner"
    GUARANTOR_PRINCIPAL = "GuarantorPrincipal"
    BANK_OFFICER = "BankOfficer"
    AUDITOR = "Auditor"


class Merchant(TypedDict, total=False):
    id: str
    legal_name: str
    state_code: str
    owner_name: str
    processing_started_at: str
    status: str
    lifetime_net_cents: int
    trailing_12m_months_recorded: int
    seasonality_index: float
    trailing_30d_net_cents: int
    prior_30d_net_cents: int
    trailing_30d_chargeback_ratio: float
    active_loan_id: Optional[str]
    loans_repaid_count: int
    created_at: str
    updated_at: str
    version: int


class ProcessingDayBatch(TypedDict, total=False):
    id: str
    merchant_id: str
    processing_date: str
    gross_cents: int
    refunds_cents: int
    chargebacks_cents: int
    net_settled_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanOffer(TypedDict, total=False):
    id: str
    merchant_id: str
    status: str
    trailing_12m_avg_net_cents: int
    seasonality_index_at_generation: float
    preapproved_standard_cents: int
    preapproved_conservative_cents: int
    preapproved_cents: int
    issued_at: Optional[str]
    expires_at: Optional[str]
    accepted_principal_cents: Optional[int]
    accepted_holdback_pct: Optional[float]
    accepted_loan_id: Optional[str]
    renewal_count: int
    generated_by: str
    created_at: str
    updated_at: str
    version: int


class Guarantor(TypedDict, total=False):
    id: str
    loan_id: str
    full_name: str
    email: str
    guarantee_cap_cents: int
    status: str
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    merchant_id: str
    offer_id: str
    principal_cents: int
    holdback_pct: float
    fee_rate: float
    fee_cents: int
    total_repayment_cents: int
    per_period_minimum_cents: int
    remaining_balance_cents: int
    paid_to_date_cents: int
    repayment_period_index: int
    consecutive_missed_periods: int
    carried_surplus_cents: int
    cumulative_shortfall_cents: int
    status: str
    disclosure_required: bool
    activated_at: Optional[str]
    servicing_retained: bool
    created_at: str
    updated_at: str
    version: int


class DisclosureStatement(TypedDict, total=False):
    id: str
    loan_id: str
    status: str
    mandate_state: bool
    apr_scheduled: float
    apr_projected: float
    disclosed_apr_basis: str
    estimated_term_days: int
    delivered_at: Optional[str]
    acknowledged_at: Optional[str]
    cooling_required: bool
    created_at: str
    updated_at: str
    version: int


class SettlementSweep(TypedDict, total=False):
    id: str
    loan_id: str
    batch_id: str
    holdback_cents: int
    clipped: bool
    swept_date: str
    status: str
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CatchUpPayment(TypedDict, total=False):
    id: str
    loan_id: str
    amount_cents: int
    period_index_credited: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict, total=False):
    id: str
    loan_id: str
    guarantor_id: str
    status: str
    demanded_at: Optional[str]
    window_end: Optional[str]
    draw_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FundingPartnerBank(TypedDict, total=False):
    id: str
    legal_name: str
    purchase_discount_pct: float
    status: str
    committed_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class LoanSale(TypedDict, total=False):
    id: str
    loan_id: str
    bank_id: str
    status: str
    purchase_price_cents: int
    reserve_withheld_cents: Optional[int]
    bank_remittance_cents: Optional[int]
    committed_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MigrationSignal(TypedDict, total=False):
    id: str
    merchant_id: str
    status: str
    drop_ratio: float
    volume_only_would_trigger: bool
    triggered: bool
    evaluated_at: str
    created_at: str
    updated_at: str
    version: int
