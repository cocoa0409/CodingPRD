"""Domain types: entity status enums, role enum, and entity TypedDicts.

Entities carrying the shared common-property shape (``id``, ``created_at``,
``updated_at``, ``version``) are declared with all four. The two append-only
evidence records — ``DeclinedAttempt`` and ``SweepIndexStamp`` — carry only
``id`` and ``created_at``.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enumerations ─────────────────────────────────────

class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AcquisitionChannel(str, Enum):
    DIRECT = "DIRECT"
    THIRD_PARTY = "THIRD_PARTY"


class VolumeTier(str, Enum):
    ACTIVITY = "ACTIVITY"
    FIXED = "FIXED"
    LOW = "LOW"


class MerchantAcceptanceStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACCEPTED = "ACCEPTED"
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    SUPPRESSED = "SUPPRESSED"


class CardProduct(str, Enum):
    GREEN = "GREEN"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"
    CENTURION = "CENTURION"


class DeclineReason(str, Enum):
    MERCHANT_NOT_ACCEPTED = "MERCHANT_NOT_ACCEPTED"
    INSUFFICIENT_CREDIT = "INSUFFICIENT_CREDIT"
    FRAUD_SUSPECT = "FRAUD_SUSPECT"
    EXPIRED_CARD = "EXPIRED_CARD"


class GapQualifiedStatus(str, Enum):
    PROSPECTING = "PROSPECTING"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"
    DORMANT = "DORMANT"


class OfferPrivacyState(str, Enum):
    DRAFT = "DRAFT"
    PRIVACY_REVIEW = "PRIVACY_REVIEW"
    MERCHANT_CONSENT = "MERCHANT_CONSENT"
    LIVE = "LIVE"
    TERMINATED = "TERMINATED"


class AudienceSegment(str, Enum):
    HIGH_SPEND = "HIGH_SPEND"
    MEDIUM_SPEND = "MEDIUM_SPEND"
    LOW_SPEND = "LOW_SPEND"
    ALL_CARDMEMBERS = "ALL_CARDMEMBERS"


class CardMemberStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    CLOSED = "CLOSED"


class LoungeAccessTier(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    UNLIMITED = "UNLIMITED"


class OfferAcceptanceStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class PoolFunder(str, Enum):
    MERCHANT = "MERCHANT"
    NETWORK = "NETWORK"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSESSED = "ASSESSED"
    DISBURSED = "DISBURSED"
    VOIDED = "VOIDED"


class ValueFundEntryKind(str, Enum):
    FEE_ALLOCATION = "FEE_ALLOCATION"
    FEE_ALLOCATION_REVERSAL = "FEE_ALLOCATION_REVERSAL"
    LOUNGE_PASS_GRANT = "LOUNGE_PASS_GRANT"


class SettlementStatus(str, Enum):
    CAPTURED = "CAPTURED"
    IN_FUNDING = "IN_FUNDING"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    MERCHANT_RESPONDED = "MERCHANT_RESPONDED"
    AUTO_ACCEPTED = "AUTO_ACCEPTED"
    WON = "WON"
    LOST = "LOST"
    WITHDRAWN = "WITHDRAWN"


class RepresentmentStage(str, Enum):
    NONE = "NONE"
    FIRST_ROUND = "FIRST_ROUND"
    CLOSED = "CLOSED"


class DisputePriority(str, Enum):
    HIGH = "HIGH"
    STANDARD = "STANDARD"


class ComplaintType(str, Enum):
    MERCHANT_NOT_ACCEPTED = "MERCHANT_NOT_ACCEPTED"
    STAFF_ATTITUDE = "STAFF_ATTITUDE"
    TERMINAL_TECHNICAL = "TERMINAL_TECHNICAL"
    PRICING_SURCHARGE = "PRICING_SURCHARGE"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class Unset(str, Enum):
    """Sentinel used by factories that must distinguish an explicitly-None
    supplied value (e.g. a clear-via-None override) from an omitted one."""
    UNSET = "__unset__"


class UserRole(str, Enum):
    NETWORK_ACQUIRER = "NetworkAcquirer"
    NETWORK_SETTLEMENT_OPS = "NetworkSettlementOps"
    NETWORK_COMPLIANCE = "NetworkCompliance"
    NETWORK_DATA_STEWARD = "NetworkDataSteward"
    NETWORK_DISPUTE_OPS = "NetworkDisputeOps"
    NETWORK_SERVICE = "NetworkService"
    NETWORK_ISSUER = "NetworkIssuer"
    MERCHANT = "Merchant"
    CARD_MEMBER = "CardMember"


# ─── Entity TypedDicts (common_fields: true) ──────────

class IndustryCategory(TypedDict):
    id: str
    industry_code: str
    industry_name: str
    risk_tier: str
    base_discount_rate_bps: int
    high_risk_flag: bool
    created_at: str
    updated_at: str
    version: int


class Merchant(TypedDict):
    id: str
    industry_category_id: str
    merchant_name: str
    region_code: str
    acquisition_channel: str
    channel_partner: Optional[str]
    volume_tier: str
    acceptance_status: str
    applied_discount_rate_bps: int
    billed_volume_mtd_cents: int
    rolling_90d_billed_volume_cents: int
    rolling_90d_settled_volume_cents: int
    last_batch_discount_fee_cents: int
    negotiated_rate_bps: Optional[int]
    reserve_required_cents: int
    reserve_held_cents: int
    status_version: int
    created_at: str
    updated_at: str
    version: int


class AcceptanceGap(TypedDict):
    id: str
    region_code: str
    industry_category_id: str
    window_start: str
    window_end: str
    window_days: int
    decline_count: int
    declined_volume_cents: int
    qualified_status: str
    sweep_index: int
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    merchant_id: str
    audience_segment: str
    min_segment_spend_cents: int
    reward_bps: int
    privacy_state: str
    audience_size: int
    aggregated_spend_cents: int
    accepted_count: int
    live_start_utc: Optional[str]
    live_end_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CardMember(TypedDict):
    id: str
    member_name: str
    card_product: str
    annual_fee_cents: int
    trailing_lowest_month_spend_cents: int
    reward_points_balance: int
    lounge_access_tier: str
    member_status: str
    created_at: str
    updated_at: str
    version: int


class OfferAcceptance(TypedDict):
    id: str
    offer_id: str
    cardmember_id: str
    trigger_amount_cents: int
    reward_amount_cents: int
    acceptance_status: str
    created_at: str
    updated_at: str
    version: int


class OfferRedemptionPool(TypedDict):
    id: str
    offer_id: str
    funder: str
    initial_funded_cents: int
    balance_cents: int
    topup_total_cents: int
    consumed_total_cents: int
    created_at: str
    updated_at: str
    version: int


class AnnualFeeStatement(TypedDict):
    id: str
    cardmember_id: str
    statement_year: int
    principal_fee_cents: int
    authorised_user_count: int
    per_user_fee_cents: int
    gross_fee_assessed_cents: int
    value_fund_allocation_cents: int
    statement_status: str
    created_at: str
    updated_at: str
    version: int


class ValueFundLedgerEntry(TypedDict):
    id: str
    source_statement_id: str
    entry_kind: str
    amount_cents: int
    created_seq: int
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    merchant_id: str
    settlement_cycle: int
    gross_volume_cents: int
    refund_volume_cents: int
    post_refund_volume_cents: int
    discount_fee_cents: int
    net_funding_cents: int
    final_discount_fee_cents: int
    final_reserve_withholding_cents: int
    funding_batch_seq: int
    finalized_at_batch_seq: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    cardmember_id: str
    final_merchant_id: str
    original_merchant_id: str
    amount_cents: int
    dispute_status: str
    representment_stage: str
    network_settled_cents: int
    chargeback_count_reserved: int
    priority: str
    created_at: str
    updated_at: str
    version: int


class AcceptanceComplaint(TypedDict):
    id: str
    merchant_id: str
    cardmember_id: str
    complaint_type: str
    complaint_status: str
    created_at: str
    updated_at: str
    version: int


class MerchantRiskState(TypedDict):
    id: str
    merchant_id: str
    rolling_chargeback_count: int
    rolling_dispute_amount_cents: int
    unresolved_chargeback_count: int
    suppression_flag: bool
    created_at: str
    updated_at: str
    version: int


# ─── Append-only evidence records (common_fields: false) ───
# These carry ONLY id and created_at: no updated_at, no version.

class DeclinedAttempt(TypedDict):
    id: str
    merchant_id: str
    card_product: str
    attempted_amount_cents: int
    decline_reason: str
    occurred_at: str
    created_at: str


class SweepIndexStamp(TypedDict):
    id: str
    sweep_index: int
    rolled_at: str
    created_at: str