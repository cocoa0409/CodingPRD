"""Domain types: entity shapes, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CREATOR = "Creator"
    MODERATOR = "Moderator"
    APPEALS_REVIEWER = "AppealsReviewer"
    SAFETY_AGENT = "SafetyAgent"
    FINANCE_OFFICER = "FinanceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AgeBand(str, Enum):
    CHILD = "CHILD"
    TEEN = "TEEN"
    ADULT = "ADULT"


class ChatFilterLevel(str, Enum):
    SAFE = "SAFE"
    STANDARD = "STANDARD"
    ADULT = "ADULT"


class ChatMode(str, Enum):
    RESTRICTED = "RESTRICTED"
    FILTERED = "FILTERED"
    OPEN = "OPEN"


class ExperienceStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class AgeRating(str, Enum):
    ALL = "ALL"
    NINE_PLUS = "NINE_PLUS"
    THIRTEEN_PLUS = "THIRTEEN_PLUS"
    SEVENTEEN_PLUS = "SEVENTEEN_PLUS"


class ModerationSubmissionStatus(str, Enum):
    QUEUED = "QUEUED"
    AUTO_REVIEWED = "AUTO_REVIEWED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


class ModerationAppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    WITHDRAWN = "WITHDRAWN"


class CurrencyPurchaseOrderStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class PurchaseOrderStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"
    REVERSED = "REVERSED"


class DevExchangeRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class MarketplaceItemStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_MODERATION = "PENDING_MODERATION"
    ON_SALE = "ON_SALE"
    OFF_SALE = "OFF_SALE"
    MODERATION_REJECTED = "MODERATION_REJECTED"


class ItemKind(str, Enum):
    HAT = "HAT"
    SHIRT = "SHIRT"
    PANTS = "PANTS"
    GEAR = "GEAR"
    LIMITED_HAT = "LIMITED_HAT"
    LIMITED_GEAR = "LIMITED_GEAR"


class ResaleListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SOLD = "SOLD"
    CANCELLED = "CANCELLED"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    ACTIONED = "ACTIONED"
    DISMISSED = "DISMISSED"


class AccountTerminationStatus(str, Enum):
    PENDING_DISPOSITION = "PENDING_DISPOSITION"
    EARNINGS_DISPOSED = "EARNINGS_DISPOSED"
    COMPLETE = "COMPLETE"


class IdentityVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class TaxDocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).

class User(TypedDict, total=False):
    id: str
    username: str
    email: str
    date_of_birth: str
    parent_user_id: Optional[str]
    status: str
    age_band: str
    account_age_days: int
    robux_balance: int
    earned_robux_lifetime: int
    is_devex_eligible: bool
    chat_filter_level: str
    suspension_reason: Optional[str]
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IdentityVerification(TypedDict, total=False):
    id: str
    user_id: str
    status: str
    document_type: str
    document_country: str
    submitted_at: str
    reviewed_at: Optional[str]
    rejection_reason: Optional[str]
    expiry_date: str
    created_at: str
    updated_at: str
    version: int


class TaxDocument(TypedDict, total=False):
    id: str
    user_id: str
    status: str
    form_type: str
    tin_last4: str
    legal_name: str
    country_of_residence: str
    submitted_at: str
    reviewed_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParentalControls(TypedDict, total=False):
    id: str
    child_user_id: str
    monthly_spend_limit_robux: Optional[int]
    chat_mode: str
    allowed_age_ratings: List[str]
    pin_hash: str
    last_changed_at: str
    created_at: str
    updated_at: str
    version: int


class Experience(TypedDict, total=False):
    id: str
    creator_user_id: str
    title: str
    description: str
    status: str
    age_rating: Optional[str]
    content_descriptors: List[str]
    visit_count_lifetime: int
    engagement_minutes_30d: int
    engagement_payout_pending_robux: int
    suspended_reason: Optional[str]
    archived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExperienceAgeRating(TypedDict, total=False):
    id: str
    experience_id: str
    rating: str
    descriptors: List[str]
    assigned_by: str
    assigned_at: str
    supersedes_id: Optional[str]
    is_current: bool
    created_at: str
    updated_at: str
    version: int


class ModerationSubmission(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    submitted_by_user_id: str
    status: str
    automated_score: Optional[float]
    reviewer_user_id: Optional[str]
    decision: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModerationAppeal(TypedDict, total=False):
    id: str
    submission_id: str
    appellant_user_id: str
    status: str
    reason: str
    reviewer_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CurrencyPurchaseOrder(TypedDict, total=False):
    id: str
    buyer_user_id: str
    fiat_amount_cents: int
    status: str
    credited_robux: Optional[int]
    payment_method_token: str
    idempotency_key: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    buyer_user_id: str
    item_type: str
    item_id: str
    status: str
    price_robux: int
    creator_credit_robux: Optional[int]
    platform_fee_robux: Optional[int]
    idempotency_key: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DevExchangeRequest(TypedDict, total=False):
    id: str
    user_id: str
    status: str
    requested_robux: int
    locked_robux: Optional[int]
    usd_payout_cents: Optional[int]
    withholding_tax_cents: Optional[int]
    net_payout_cents: Optional[int]
    submitted_at: str
    approved_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketplaceItem(TypedDict, total=False):
    id: str
    creator_user_id: str
    title: str
    item_kind: str
    price_robux: int
    status: str
    total_supply: Optional[int]
    copies_sold: int
    is_limited: bool
    royalty_pct: int
    moderation_submission_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResaleListing(TypedDict, total=False):
    id: str
    item_id: str
    seller_user_id: str
    status: str
    ask_price_robux: int
    listed_at: str
    sold_at: Optional[str]
    buyer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChatMessage(TypedDict, total=False):
    id: str
    experience_id: str
    sender_user_id: str
    body_raw: str
    body_filtered: str
    filter_applied: str
    was_reported: bool
    sent_at: str
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict, total=False):
    id: str
    message_id: str
    reporter_user_id: str
    reason_code: str
    status: str
    triaged_by_user_id: Optional[str]
    triaged_at: Optional[str]
    action_taken: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccountTermination(TypedDict, total=False):
    id: str
    user_id: str
    initiated_by_user_id: str
    reason_code: str
    status: str
    earnings_disposition: Optional[str]
    disposed_robux: Optional[int]
    disposed_usd_cents: Optional[int]
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only rows: only id + created_at (PRD §2.4); no updated_at / version.

class EngagementSnapshot(TypedDict, total=False):
    id: str
    experience_id: str
    snapshot_date: str
    minutes_engaged: int
    payout_robux: int
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    actor_user_id: str
    action: str
    subject_type: str
    subject_id: str
    payload: Dict[str, Any]
    at: str
    created_at: str
