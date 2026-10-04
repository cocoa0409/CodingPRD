"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the entity and state-machine surface described in the PRD
(§2.4 membership standing, §2.5 deposit ledger, §2.6 trade state dimensions,
§2.7 settlement cycles, §2.10 common resource properties).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Enums ────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLEARING_MEMBER = "ClearingMember"
    RISK_OFFICER = "RiskOfficer"


class ParticipantClass(str, Enum):
    BANK = "BANK"
    BROKER_DEALER = "BROKER_DEALER"
    CUSTODIAN_BANK = "CUSTODIAN_BANK"
    INSURANCE_CARRIER = "INSURANCE_CARRIER"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEFAULTED = "DEFAULTED"
    EXPELLED = "EXPELLED"


class FinancialStandardStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class DepositStatus(str, Enum):
    PENDING = "PENDING"
    SATISFIED = "SATISFIED"
    DEFICIENT_GRACE = "DEFICIENT_GRACE"
    DEFICIENT_DEFAULT = "DEFICIENT_DEFAULT"


class DepositTxnType(str, Enum):
    POST = "POST"
    RELEASE = "RELEASE"


class LockStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED_IN = "LOCKED_IN"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class MatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    ALLEGED = "ALLEGED"
    UNRESOLVED = "UNRESOLVED"


class AffirmationStatus(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"
    AFFIRMED = "AFFIRMED"
    UNCONFIRMED_BREACH = "UNCONFIRMED_BREACH"


class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class CustodyAccountType(str, Enum):
    SEGREGATED = "SEGREGATED"
    HOUSE = "HOUSE"
    PLEDGED = "PLEDGED"


class CustodyAccountStatus(str, Enum):
    OPEN = "OPEN"
    PLEDGED = "PLEDGED"
    FROZEN = "FROZEN"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    NETTED = "NETTED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class DvpStatus(str, Enum):
    FUNDED = "FUNDED"
    DELIVERED = "DELIVERED"
    RECEIVED = "RECEIVED"
    FAILED = "FAILED"


class CorporateActionType(str, Enum):
    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    CASH_DIVIDEND = "CASH_DIVIDEND"


class CorporateActionStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class ClearingFundStatus(str, Enum):
    OPEN = "OPEN"
    RECOMPUTED = "RECOMPUTED"


class FundComponentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    COLLECTED = "COLLECTED"
    RELEASED = "RELEASED"


class DefaultProceedingStatus(str, Enum):
    DECLARED = "DECLARED"
    LIQUIDATING = "LIQUIDATING"
    LIQUIDATED = "LIQUIDATED"
    ALLOCATED = "ALLOCATED"


# ─── Entity TypedDicts: common field set (id, created_at, updated_at, version) ───

class Participant(TypedDict):
    id: str
    legal_name: str
    lei: str
    participant_class: str
    membership_status: str
    net_capital_cents: int
    required_min_net_capital_cents: int
    financial_standard_status: str
    is_defaulted: bool
    requires_segregated_custody: bool
    last_financial_review_at: str
    created_at: str
    updated_at: str
    version: int


class ClearingMemberDeposit(TypedDict):
    id: str
    participant_id: str
    posted_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeSubmission(TypedDict):
    id: str
    participant_id: str
    counterparty_participant_id: str
    security_id: str
    side: str
    quantity: int
    trade_price_cents: int
    trade_date: str
    lock_status: str
    match_status: str
    affirmation_status: str
    allegations_received: int
    created_at: str
    updated_at: str
    version: int


class Security(TypedDict):
    id: str
    ticker: str
    cusip: str
    currency: str
    prev_settlement_price_cents: int
    current_volatility_bps: int
    created_at: str
    updated_at: str
    version: int


class CustodyAccount(TypedDict):
    id: str
    participant_id: str
    account_number: str
    account_type: str
    status: str
    positions: List[dict]
    created_at: str
    updated_at: str
    version: int


class SettlementWindow(TypedDict):
    id: str
    security_id: str
    settlement_date: str
    trade_entry_deadline: str
    affirmation_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NetPosition(TypedDict):
    id: str
    window_id: str
    participant_id: str
    security_id: str
    net_quantity: int
    cash_delta_cents: int
    settlement_obligation_cents: int
    dvp_status: str
    funded_amount_cents: int
    failed_at: Optional[str]
    failed_at_price_cents: Optional[int]
    mark_to_market_cents: int
    created_at: str
    updated_at: str
    version: int


class CorporateAction(TypedDict):
    id: str
    security_id: str
    action_type: str
    ratio_numerator: int
    ratio_denominator: int
    cash_rate_cents_per_unit: int
    effective_date: str
    status: str
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClearingFund(TypedDict):
    id: str
    security_id: str
    status: str
    fund_balance_cents: int
    total_component_cents: int
    last_computed_at: Optional[str]
    participant_class: str
    experiences_deficit: bool
    created_at: str
    updated_at: str
    version: int


class FundComponent(TypedDict):
    id: str
    clearing_fund_id: str
    participant_id: str
    component_amount_cents: int
    component_balance_cents: int
    generation: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DefaultProceeding(TypedDict):
    id: str
    participant_id: str
    reason_code: str
    status: str
    liquidation_proceeds_cents: int
    deficit_amount_cents: int
    defaulter_resources_cents: int
    allocated_total_cents: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only ledgers: id + created_at ONLY (no updated_at, no version) ───

class DepositTransaction(TypedDict):
    id: str
    deposit_id: str
    participant_id: str
    amount_cents: int
    txn_type: str
    reason_code: Optional[str]
    created_at: str


class LossAllocationTransaction(TypedDict):
    id: str
    default_proceeding_id: str
    fund_component_id: str
    amount_cents: int
    posted_at: str
    created_at: str