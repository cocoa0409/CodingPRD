"""Enumerations and record shapes declared by the PRD.

Symbol spellings are the PRD's own; every call site in the suite uses these
members rather than bare strings so that one spelling is impossible to drift.
"""
from enum import Enum
from typing import Optional, TypedDict


class Role(str, Enum):
    GPO_ADMIN = "GpoAdmin"
    REBATE_ANALYST = "RebateAnalyst"
    DISPUTE_ARBITER = "DisputeArbiter"
    MEMBER_OPERATOR = "MemberOperator"
    DISTRIBUTOR_FEED = "DistributorFeed"
    MANUFACTURER_REP = "ManufacturerRep"


class TierCode(str, Enum):
    CORE = "CORE"
    PLUS = "PLUS"
    ELITE = "ELITE"


class MemberEnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ReconciliationPosture(str, Enum):
    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"


class DistributorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LetterStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class LetterScope(str, Enum):
    PURCHASE_DATA_ONLY = "PURCHASE_DATA_ONLY"
    PURCHASE_DATA_AND_PRICING = "PURCHASE_DATA_AND_PRICING"


class CountersignDecision(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class DealStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    LOST = "LOST"


class ItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELISTED = "DELISTED"


class RateCardStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class RateType(str, Enum):
    PER_CASE = "PER_CASE"
    PERCENT_OF_SPEND = "PERCENT_OF_SPEND"
    TIERED_VOLUME = "TIERED_VOLUME"


class NormalizationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    NORMALIZED = "NORMALIZED"
    ACCRUED = "ACCRUED"


class AuditStatus(str, Enum):
    NOT_AUDITED = "NOT_AUDITED"
    AUDIT_CLEAN = "AUDIT_CLEAN"
    AUDIT_OVERBILLED = "AUDIT_OVERBILLED"
    RECOVERY_REQUESTED = "RECOVERY_REQUESTED"
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


class MatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    EXCLUDED = "EXCLUDED"


class AccrualBlockReason(str, Enum):
    NONE = "NONE"
    NO_RATE_CARD = "NO_RATE_CARD"
    ITEM_DELISTED = "ITEM_DELISTED"
    DEAL_NOT_ACTIVE = "DEAL_NOT_ACTIVE"


class AccrualStatus(str, Enum):
    ACCRUED = "ACCRUED"
    VALIDATED = "VALIDATED"
    FLAGGED = "FLAGGED"
    DISPUTED = "DISPUTED"
    REVERSED = "REVERSED"
    PAID = "PAID"


class AccrualBasis(str, Enum):
    MARGINAL_BATCH = "MARGINAL_BATCH"
    BLENDED_PERIOD = "BLENDED_PERIOD"


class ReversalReason(str, Enum):
    NONE = "NONE"
    DISPUTE_UPHELD = "DISPUTE_UPHELD"
    RENORMALIZED = "RENORMALIZED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECONCILED = "RECONCILED"
    VARIANCE_FLAGGED = "VARIANCE_FLAGGED"
    SUPERSEDED = "SUPERSEDED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class DisputeReasonCode(str, Enum):
    RATE_MISMATCH = "RATE_MISMATCH"
    UNITS_MISMATCH = "UNITS_MISMATCH"
    ITEM_MISMATCH = "ITEM_MISMATCH"
    TIER_MISMATCH = "TIER_MISMATCH"


class DisputeDecision(str, Enum):
    UPHOLD = "UPHOLD"
    REJECT = "REJECT"


class ComplianceResult(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    BREACH = "BREACH"
    DEAL_LOST = "DEAL_LOST"


class SavingsBasis(str, Enum):
    AS_PURCHASED = "AS_PURCHASED"
    FULL_BASKET = "FULL_BASKET"


class RecoveryOutcome(str, Enum):
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


class TierBreak(TypedDict):
    min_cases: int
    rate_cents_per_case: int


class ProgramTierPayload(TypedDict, total=False):
    tier_code: str
    member_share_bps: int
    gpo_retention_bps: int
    admin_fee_bps_low: int
    admin_fee_bps_high: int
    compliance_min_ratio_bps: int
    markup_cap_bps: int
    dispute_window_days: int
    reversal_posture_limit: int


class DistributorPayload(TypedDict, total=False):
    name: str
    dba_code: str
    contracted_markup_bps: int


class MemberPayload(TypedDict, total=False):
    legal_name: str
    tier_id: str
    committed_annual_spend_cents: int


class AuthorizationLetterPayload(TypedDict, total=False):
    member_id: str
    distributor_id: str
    effective_from: str
    effective_to: str
    signatory_name: str
    scope: str


class ManufacturerDealPayload(TypedDict, total=False):
    manufacturer_name: str
    deal_code: str
    effective_from: str
    effective_to: str
    required_purchase_window_days: int


class ContractedItemPayload(TypedDict, total=False):
    deal_id: str
    manufacturer_sku: str
    normalized_item_key: str
    pack_size: int
    baseline_unit_cost_cents: int
    contract_unit_cost_cents: int


class RateCardPayload(TypedDict, total=False):
    contracted_item_id: str
    expected_contracted_item_version: int
    rate_type: str
    flat_rate_cents_per_case: int
    percent_bps: int
    tier_breaks: list
    effective_from: str
    effective_to: str
    supersede: bool


class PurchaseBatchPayload(TypedDict, total=False):
    distributor_id: str
    period_start: str
    period_end: str
    source_reference: str


class PurchaseLinePayload(TypedDict, total=False):
    purchase_batch_id: str
    member_id: str
    distributor_sku: str
    vendor_item_description: str
    normalized_item_key_reported: str
    cases_shipped: int
    invoice_unit_cost_cents: int
    distributor_base_cost_cents: int
    invoice_date: str


class ManufacturerClaimPayload(TypedDict, total=False):
    deal_id: str
    expected_deal_version: int
    period_start: str
    period_end: str
    claimed_units: int
    claimed_amount_cents: int


class DisputePayload(TypedDict, total=False):
    accrual_id: str
    claim_id: Optional[str]
    reason_code: str
    disputed_amount_cents: int


class ComplianceReviewPayload(TypedDict, total=False):
    member_id: str
    deal_id: str
    window_start: str
    window_end: str
