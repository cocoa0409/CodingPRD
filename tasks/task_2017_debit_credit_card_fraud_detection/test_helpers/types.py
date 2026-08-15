"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    FRAUD_ANALYST = "FraudAnalyst"
    FRAUD_OPS_MANAGER = "FraudOpsManager"
    LOSS_ACCOUNTANT = "LossAccountant"
    RECOVERY_SPECIALIST = "RecoverySpecialist"
    CARDHOLDER = "Cardholder"
    NETWORK_GATEWAY = "NetworkGateway"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SOFT_BLOCKED = "SOFT_BLOCKED"
    HARD_CLOSED = "HARD_CLOSED"
    REPLACED = "REPLACED"


class FraudFlag(str, Enum):
    CLEAN = "CLEAN"
    WATCH = "WATCH"
    COMPROMISED = "COMPROMISED"


class BlockReason(str, Enum):
    ANALYST_REVIEW = "ANALYST_REVIEW"
    CONFIRMED_FRAUD = "CONFIRMED_FRAUD"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    COMPROMISE_EVENT = "COMPROMISE_EVENT"


class RuleSetStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RuleSetScope(str, Enum):
    GLOBAL = "GLOBAL"
    DEBIT_CARD = "DEBIT_CARD"
    CREDIT_CARD = "CREDIT_CARD"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    DECLINE = "DECLINE"


class DecisionReason(str, Enum):
    RULE_SCORE = "RULE_SCORE"
    CARD_BLOCKED = "CARD_BLOCKED"


class FinalDisposition(str, Enum):
    UNDISPOSED = "UNDISPOSED"
    CONFIRMED_FRAUD = "CONFIRMED_FRAUD"
    CONFIRMED_LEGIT = "CONFIRMED_LEGIT"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    CONTACT_PENDING = "CONTACT_PENDING"
    RESOLVED_FRAUD = "RESOLVED_FRAUD"
    RESOLVED_LEGIT = "RESOLVED_LEGIT"
    EXPIRED = "EXPIRED"


class AlertSource(str, Enum):
    SCORING_REVIEW = "SCORING_REVIEW"
    MANUAL = "MANUAL"


class Resolution(str, Enum):
    FRAUD = "FRAUD"
    LEGIT = "LEGIT"


class ContactChannel(str, Enum):
    VOICE = "VOICE"
    SMS = "SMS"
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"


class ContactStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class ContactOutcome(str, Enum):
    CONFIRMED_FRAUD = "CONFIRMED_FRAUD"
    CONFIRMED_LEGIT = "CONFIRMED_LEGIT"
    UNREACHABLE = "UNREACHABLE"


class NetworkSource(str, Enum):
    CAMS = "CAMS"
    ADC = "ADC"


class EventStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CONFIRMED = "CONFIRMED"
    CLOSED = "CLOSED"


class ReissueDecisionValue(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    AUTO_APPROVED = "AUTO_APPROVED"


class NoticeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CbStatus(str, Enum):
    FILED = "FILED"
    PROVISIONAL_CREDIT_POSTED = "PROVISIONAL_CREDIT_POSTED"
    REPRESENTMENT_FILED = "REPRESENTMENT_FILED"
    RESOLVED_WON = "RESOLVED_WON"
    RESOLVED_LOST = "RESOLVED_LOST"
    WITHDRAWN = "WITHDRAWN"


class LossStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    BOOKED = "BOOKED"
    FINALIZED = "FINALIZED"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    FULLY_RECOVERED = "FULLY_RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


class FilingStatus(str, Enum):
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class RingStatus(str, Enum):
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


# --- Entity TypedDicts (all resources carry the full common-field set:
# id, created_at, updated_at, version) ---


class Account(TypedDict):
    id: str
    account_number: str
    cardholder_name: str
    home_country: str
    account_status: str
    credit_balance_cents: int
    open_alert_count: int
    rolling_90d_loss_cents: int
    risk_tier: str
    created_at: str
    updated_at: str
    version: int


class Card(TypedDict):
    id: str
    account_id: str
    pan_token: str
    product_type: str
    network: str
    card_status: str
    fraud_flag: str
    block_reason: Optional[str]
    replaces_card_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RuleSet(TypedDict):
    id: str
    scope: str
    base_score: int
    review_threshold: int
    decline_threshold: int
    amount_tiers: list
    channel_weights: dict
    cross_border_weight: int
    high_risk_multiplier: float
    watch_weight: int
    compromised_weight: int
    high_risk_countries: list
    ruleset_status: str
    created_by_user_id: str
    activated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuthTransaction(TypedDict):
    id: str
    card_id: str
    account_id: str
    ruleset_id: Optional[str]
    amount_cents: int
    currency: str
    merchant_id: str
    merchant_category_code: str
    channel: str
    origin_country: str
    home_country: str
    scored_at: str
    auth_score: Optional[int]
    decision: str
    decision_reason: str
    shadow_score: Optional[int]
    shadow_decision: Optional[str]
    shadow_ruleset_id: Optional[str]
    final_disposition: str
    created_at: str
    updated_at: str
    version: int


class FraudAlert(TypedDict):
    id: str
    account_id: str
    card_id: str
    auth_transaction_id: Optional[str]
    source: str
    alert_status: str
    band_points: int
    priority: int
    assigned_to_user_id: Optional[str]
    reopen_count: int
    resolution: Optional[str]
    fraud_credit_cents: int
    sla_expires_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VerificationContact(TypedDict):
    id: str
    alert_id: str
    account_id: str
    channel: str
    contact_status: str
    outcome: Optional[str]
    contacted_at: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class CompromisedCardEvent(TypedDict):
    id: str
    network_source: str
    event_reference: str
    merchant_id: str
    window_start: str
    window_end: str
    event_status: str
    affected_card_count: int
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReissueDecision(TypedDict):
    id: str
    event_id: str
    card_id: str
    replacement_card_id: Optional[str]
    decision: str
    exposure_cents: int
    due_at: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TravelNotice(TypedDict):
    id: str
    card_id: str
    region_country: str
    start_date: str
    end_date: str
    notice_status: str
    created_at: str
    updated_at: str
    version: int


class ChargebackCase(TypedDict):
    id: str
    auth_transaction_id: str
    account_id: str
    reason_code: str
    provisional_credit_cents: int
    cb_status: str
    created_at: str
    updated_at: str
    version: int


class LossEntry(TypedDict):
    id: str
    account_id: str
    transaction_ids: List[str]
    provisional_amount_cents: int
    tolerance_cents: int
    final_amount_cents: Optional[int]
    outstanding_cents: int
    written_off_cents: int
    loss_status: str
    booked_by_user_id: Optional[str]
    booked_at: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecoveryFiling(TypedDict):
    id: str
    loss_entry_id: str
    network_reference: str
    claimed_cents: int
    paid_cents: Optional[int]
    filing_status: str
    filed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class FraudRing(TypedDict):
    id: str
    signal_type: str
    merchant_id: str
    window_start: str
    window_end: str
    ring_status: str
    member_count: int
    created_at: str
    updated_at: str
    version: int


class RingMembership(TypedDict):
    id: str
    ring_id: str
    account_id: str
    evidence_txn_count: int
    created_at: str
    updated_at: str
    version: int
