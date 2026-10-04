"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD: primary resources carry id/created_at/updated_at/version;
append-only ledger resources (ClaimPayment, PolicyLedgerEntry) carry only
id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


class RateFilingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class FilingMode(str, Enum):
    ABSOLUTE_CENTS = "ABSOLUTE_CENTS"
    PCT_OF_PREMIUM = "PCT_OF_PREMIUM"


class FeeConfigStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TreatyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CauseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CohortStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DONATED = "DONATED"
    EXPIRED = "EXPIRED"


class PolicyholderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEBARRED = "DEBARRED"


class QuoteStatus(str, Enum):
    OPEN = "OPEN"
    BOUND = "BOUND"
    EXPIRED = "EXPIRED"


class ApplicationStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    FNOL_SUBMITTED = "FNOL_SUBMITTED"
    AUTO_APPROVED = "AUTO_APPROVED"
    ESCALATED = "ESCALATED"
    PAID = "PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"


class DenialReason(str, Enum):
    FRAUD = "FRAUD"
    COVERAGE = "COVERAGE"
    OTHER = "OTHER"


class ClaimPaymentStatus(str, Enum):
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class LedgerEntryKind(str, Enum):
    PREMIUM_CHARGE = "PREMIUM_CHARGE"
    FEE_RETAINED = "FEE_RETAINED"
    REINSURANCE_CEDED = "REINSURANCE_CEDED"
    CLAIM_PAYOUT = "CLAIM_PAYOUT"
    CLAIM_PAYOUT_REVERSAL = "CLAIM_PAYOUT_REVERSAL"


class AppealStatus(str, Enum):
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    POLICYHOLDER = "Policyholder"
    UNDERWRITING_ADMIN = "UnderwritingAdmin"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    FINANCE_OPS = "FinanceOps"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Primary resources (id + created_at + updated_at + version) ---


class RateFiling(TypedDict, total=False):
    id: str
    state_code: str
    max_flat_fee_pct: float
    max_flat_fee_cap_cents: Optional[int]
    filing_mode: str
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeConfig(TypedDict, total=False):
    id: str
    state_code: str
    filing_id: str
    flat_fee_pct: float
    flat_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReinsuranceTreaty(TypedDict, total=False):
    id: str
    name: str
    quota_share_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Cause(TypedDict, total=False):
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Cohort(TypedDict, total=False):
    id: str
    cohort_year: int
    cause_id: str
    status: str
    premium_pool_cents: int
    fee_retained_cents: int
    reinsurance_ceded_cents: int
    claims_pot_cents: int
    retained_claims_actual_cents: int
    retained_claims_reserved_cents: int
    giveback_actual_cents: int
    giveback_projected_cents: int
    created_at: str
    updated_at: str
    version: int


class Policyholder(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    state_code: str
    fraud_strike_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    policyholder_id: str
    coverage_amount_cents: int
    premium_cents: int
    state_code: str
    expires_at: str
    premium_grace_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PolicyApplication(TypedDict, total=False):
    id: str
    policyholder_id: str
    quote_id: str
    checkout_velocity_seconds: int
    device_reuse_count: int
    answers_ipa_acknowledged: bool
    behavioral_signal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    policyholder_id: str
    quote_id: str
    cohort_id: str
    fee_config_id: str
    annual_premium_cents: int
    premium_paid_cents: int
    premium_outstanding_cents: int
    fraud_flag: bool
    cause_id: Optional[str]
    cause_election_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    policy_id: str
    video_statement_ref: str
    claimed_amount_cents: int
    fraud_score: float
    payout_cents: Optional[int]
    reserve_cents: Optional[int]
    reinsurance_share_cents: int
    denial_reason: Optional[str]
    denied_by_adjuster_id: Optional[str]
    appeal_deadline: Optional[str]
    appeal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    claim_id: str
    statement: str
    review_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger resources (id + created_at ONLY) ---


class ClaimPayment(TypedDict, total=False):
    id: str
    claim_id: str
    amount_cents: int
    reinsurance_share_cents: int
    fee_cents: int
    status: str
    created_at: str


class PolicyLedgerEntry(TypedDict, total=False):
    id: str
    policy_id: str
    kind: str
    amount_cents: int
    claim_id: Optional[str]
    created_at: str
