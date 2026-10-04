"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class DeveloperAccountStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class TitleStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    RELEASE_SCHEDULED = "RELEASE_SCHEDULED"
    RELEASED = "RELEASED"
    DELISTED = "DELISTED"


class StorePageReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RegionPriceOverrideStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class ActivationKeyBatchStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ActivationKeyStatus(str, Enum):
    UNUSED = "UNUSED"
    REDEEMED = "REDEEMED"
    REVOKED = "REVOKED"


class UserAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    BANNED = "BANNED"


class PurchaseStatus(str, Enum):
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class RefundRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReviewStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    REMOVED = "REMOVED"


class ReviewBombWindowStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class WorkshopItemStatus(str, Enum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    REMOVED = "REMOVED"


class RecentReviewSummary(str, Enum):
    MOSTLY_POSITIVE = "MOSTLY_POSITIVE"
    MIXED = "MIXED"
    MOSTLY_NEGATIVE = "MOSTLY_NEGATIVE"


class UserRole(str, Enum):
    PLATFORM_OPS = "PlatformOps"
    DEVELOPER = "Developer"
    STORE_REVIEWER = "StoreReviewer"
    TRUST_SAFETY = "TrustSafety"
    USER = "User"
    ANONYMOUS = "Anonymous"


class DeveloperAccount(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    onboarding_fee_paid: bool
    bank_details_submitted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict, total=False):
    id: str
    developer_account_id: str
    title_name: str
    base_price_usd_cents: int
    early_access: bool
    early_access_disclosure_text: Optional[str]
    status: str
    review_notes: Optional[str]
    scheduled_release_at: Optional[str]
    released_at: Optional[str]
    current_tier: int
    lifetime_recognized_revenue_usd_cents: int
    lifetime_refund_events: int
    refund_abuse_flag: bool
    review_score_bps: Optional[int]
    recent_review_summary: Optional[str]
    review_bomb_flag: bool
    created_at: str
    updated_at: str
    version: int


class StorePageReview(TypedDict, total=False):
    id: str
    title_id: str
    submission_seq: int
    submitted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RegionPriceOverride(TypedDict, total=False):
    id: str
    title_id: str
    currency: str
    price_cents: int
    status: str
    deviation_bps: int
    created_at: str
    updated_at: str
    version: int


class ActivationKeyBatch(TypedDict, total=False):
    id: str
    title_id: str
    requested_quantity: int
    free_keys_in_batch: int
    status: str
    free_key_allowance_at_request: int
    allocated_keys: int
    created_at: str
    updated_at: str
    version: int


class ActivationKey(TypedDict, total=False):
    id: str
    batch_id: str
    key_code: str
    is_free: bool
    status: str
    redeemed_by_account_id: Optional[str]
    redeemed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UserAccount(TypedDict, total=False):
    id: str
    email: str
    status: str
    refund_abuse_score: int
    refund_restricted: bool
    created_at: str
    updated_at: str
    version: int


class Purchase(TypedDict, total=False):
    id: str
    user_account_id: str
    title_id: str
    currency: str
    gross_price_cents: int
    platform_fee_cents: int
    developer_share_cents: int
    usd_recognized_cents: int
    status: str
    refunded_amount_usd_cents: int
    playtime_minutes: int
    refunded_cents: int
    purchased_at: str
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict, total=False):
    id: str
    purchase_id: str
    user_account_id: str
    amount_cents: int
    reason: str
    status: str
    decision_reason: Optional[str]
    approved_amount_cents: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict, total=False):
    id: str
    title_id: str
    user_account_id: str
    is_positive: bool
    body: str
    author_playtime_minutes: int
    status: str
    off_topic: bool
    created_at: str
    updated_at: str
    version: int


class ReviewBombWindow(TypedDict, total=False):
    id: str
    title_id: str
    start_at: str
    end_at: str
    status: str
    trigger_review_count: int
    created_at: str
    updated_at: str
    version: int


class WorkshopItem(TypedDict, total=False):
    id: str
    title_id: str
    creator_account_id: str
    item_name: str
    price_cents: int
    creator_share_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkshopSale(TypedDict, total=False):
    id: str
    workshop_item_id: str
    buyer_account_id: str
    gross_cents: int
    creator_share_cents: int
    platform_share_cents: int
    sold_at: str
    created_at: str
    updated_at: str
    version: int
