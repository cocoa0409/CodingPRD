"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    ADVERTISER = "Advertiser"
    POLICY_REVIEWER = "PolicyReviewer"
    BILLING_ADMIN = "BillingAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"


class AdvertiserAccountStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    APPEAL_PENDING = "APPEAL_PENDING"
    SUSPENDED_FINAL = "SUSPENDED_FINAL"


class SuspensionReasonCode(str, Enum):
    POLICY_VIOLATION = "POLICY_VIOLATION"
    CIRCUMVENTION = "CIRCUMVENTION"
    BILLING_DELINQUENCY = "BILLING_DELINQUENCY"


class IdentityVerificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DocumentType(str, Enum):
    BUSINESS_LICENSE = "BUSINESS_LICENSE"
    TAX_CERTIFICATE = "TAX_CERTIFICATE"
    GOVERNMENT_ID = "GOVERNMENT_ID"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class PaymentMethodType(str, Enum):
    CARD = "CARD"
    INVOICING = "INVOICING"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class PauseOrigin(str, Enum):
    NONE = "NONE"
    ADVERTISER = "ADVERTISER"
    SUSPENSION = "SUSPENSION"
    NO_ELIGIBLE_ADS = "NO_ELIGIBLE_ADS"


class AdStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    ELIGIBLE = "ELIGIBLE"
    DISAPPROVED = "DISAPPROVED"


class AdCategory(str, Enum):
    GENERAL = "GENERAL"
    ALCOHOL = "ALCOHOL"
    GAMBLING = "GAMBLING"
    HEALTHCARE = "HEALTHCARE"
    FINANCIAL = "FINANCIAL"


class MatchType(str, Enum):
    EXACT = "EXACT"
    PHRASE = "PHRASE"
    BROAD = "BROAD"


class AutomatedVerdict(str, Enum):
    CLEAN = "CLEAN"
    FLAGGED_RESTRICTED = "FLAGGED_RESTRICTED"


class PolicyReviewOutcome(str, Enum):
    PENDING_AUTO = "PENDING_AUTO"
    AUTO_APPROVED = "AUTO_APPROVED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    HUMAN_VIOLATION = "HUMAN_VIOLATION"


class InvoiceKind(str, Enum):
    THRESHOLD = "THRESHOLD"
    MONTHLY = "MONTHLY"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"


# --- Entity TypedDicts (all carry common fields: id, created_at, updated_at, version) ---


class AdvertiserAccount(TypedDict, total=False):
    id: str
    business_name: str
    country_code: str
    status: str
    suspension_reason_code: Optional[str]
    suspended_at: Optional[str]
    upheld_appeal_count: int
    verified_business_name: Optional[str]
    disclosure_text: Optional[str]
    lifetime_valid_served_cents: int
    lifetime_billed_cents: int
    lifetime_overdelivery_credit_cents: int
    lifetime_invalid_click_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class IdentityVerification(TypedDict, total=False):
    id: str
    account_id: str
    legal_business_name: str
    registration_number: str
    document_type: str
    disclosure_consent: bool
    status: str
    rejection_reason: Optional[str]
    supersedes_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    account_id: str
    argument_text: str
    challenges_suspended_at: Optional[str]
    status: str
    decided_at: Optional[str]
    reviewer_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingProfile(TypedDict, total=False):
    id: str
    account_id: str
    payment_method_type: str
    currency_code: str
    billing_threshold_cents: int
    unbilled_cost_cents: int
    pending_credit_cents: int
    outstanding_balance_cents: int
    last_closed_month: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    account_id: str
    name: str
    daily_budget_cents: int
    start_date: str
    end_date: str
    eligible_ad_count: int
    status: str
    pause_origin: str
    served_lifetime_cents: int
    click_count_lifetime: int
    current_month_served_cents: int
    overdelivery_credit_cents: int
    monthly_cap_provisional_cents: int
    last_closed_month_cap_cents: Optional[int]
    last_closed_month_credit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AdGroup(TypedDict, total=False):
    id: str
    campaign_id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class Ad(TypedDict, total=False):
    id: str
    ad_group_id: str
    headline: str
    final_url: str
    category: str
    restricted_category_certified: bool
    quality_ectr_score: int
    quality_relevance_score: int
    quality_lp_score: int
    quality_score_snapshot_centi: Optional[int]
    status: str
    review_round: int
    created_at: str
    updated_at: str
    version: int


class Keyword(TypedDict, total=False):
    id: str
    ad_group_id: str
    text: str
    normalized_text: str
    match_type: str
    is_negative: bool
    max_cpc_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PolicyReview(TypedDict, total=False):
    id: str
    ad_id: str
    round: int
    automated_verdict: str
    outcome: str
    reviewer_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuctionEvent(TypedDict, total=False):
    id: str
    query_text: str
    clicked: bool
    is_invalid_click: bool
    occurred_date: str
    winner_ad_id: str
    winner_campaign_id: str
    winner_ad_rank: int
    runner_up_ad_rank: Optional[int]
    quality_score_final_centi: int
    charged_cents: int
    created_at: str
    updated_at: str
    version: int


class DailySpendRecord(TypedDict, total=False):
    id: str
    campaign_id: str
    spend_date: str
    served_cents: int
    click_count: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    billing_profile_id: str
    kind: str
    period_start: str
    period_end: str
    amount_cents: int
    overdelivery_credit_cents: int
    invalid_click_credit_cents: int
    status: str
    due_date: str
    paid_cents: int
    created_at: str
    updated_at: str
    version: int
