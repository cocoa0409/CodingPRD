"""Domain types for the Creator Monetization Claims API: status enums, role
enum and entity TypedDicts (PRD §2.5, §3).

Entities declared with the common field set carry id + created_at + updated_at
+ version.  The sub-resources declared without it (AdReview, ClaimDispute,
ClaimAppeal, RevenueRouting, RevenueEvent) carry only id + their own creation
timestamp.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Enumerations ─────────────────────────────────────

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CREATOR = "Creator"
    MONETIZATION_REVIEWER = "MonetizationReviewer"
    REVIEWER = "Reviewer"
    RIGHTS_HOLDER = "RightsHolder"
    MODERATOR = "Moderator"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANY = "Any"


class MonetizationStatus(str, Enum):
    NOT_APPLIED = "MONETIZATION_NOT_APPLIED"
    PENDING = "MONETIZATION_PENDING"
    APPROVED = "MONETIZATION_APPROVED"
    REJECTED = "MONETIZATION_REJECTED"
    REVOKED = "MONETIZATION_REVOKED"


class MonetizationPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class UploadStatus(str, Enum):
    UPLOADED = "UPLOADED"
    CLASSIFYING = "CLASSIFYING"
    CLASSIFIED = "CLASSIFIED"
    CLAIM_SCAN_COMPLETE = "CLAIM_SCAN_COMPLETE"


class AdSuitability(str, Enum):
    AD_FRIENDLY = "AD_FRIENDLY"
    LIMITED_ADS = "LIMITED_ADS"
    NO_ADS = "NO_ADS"


class ClaimStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISPUTED = "DISPUTED"
    APPEALED = "APPEALED"
    REINSTATED = "REINSTATED"
    RELEASED = "RELEASED"
    TAKEN_DOWN = "TAKEN_DOWN"


class ClaimLockReason(str, Enum):
    NONE = "NONE"
    PENDING_RETRO = "PENDING_RETRO"
    RETROACTIVE_OWED = "RETROACTIVE_OWED"


class ClaimLevel(str, Enum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class StreamType(str, Enum):
    AD = "AD"
    MEMBERSHIP = "MEMBERSHIP"
    SUPER_CHAT = "SUPER_CHAT"
    SHOPPING = "SHOPPING"


class RoutingStatus(str, Enum):
    ESCROW = "ESCROW"
    PAID_CREATOR = "PAID_CREATOR"
    RETROACTIVE_OWED = "RETROACTIVE_OWED"
    RELEASED_TO_CREATOR = "RELEASED_TO_CREATOR"


class PayoutStage(str, Enum):
    ROUTE = "ROUTE"
    PAYOUT = "PAYOUT"


class PayoutStatus(str, Enum):
    LOCKED = "LOCKED"
    RELEASED = "RELEASED"
    FAILED = "FAILED"


class StrikeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class TinStatus(str, Enum):
    MISSING = "TIN_MISSING"
    PROVIDED = "TIN_PROVIDED"


# ─── Entities with the common field set ───────────────

class Channel(TypedDict, total=False):
    id: str
    channel_name: str
    country_code: str
    lifetime_watch_hours: int
    subscriber_count: int
    policy_strike_count: int
    copyright_strike_count: int
    last_copyright_strike_activated_at: Optional[str]
    monetization_status: str
    monetization_posture: str
    membership_offered: bool
    tax_tin_status: str
    tax_treaty: bool
    payment_threshold_cents: int
    created_at: str
    updated_at: str
    version: int


class ContentItem(TypedDict, total=False):
    id: str
    channel_id: str
    title: str
    duration_seconds: int
    category_code: str
    self_declared_mature: bool
    upload_status: str
    ad_suitability: Optional[str]
    limited_ads_reasons: List[str]
    gross_revenue_cents: int
    routed_revenue_cents: int
    holds_revenue: bool
    takedown_flag: bool
    created_at: str
    updated_at: str
    version: int


class ReferenceFile(TypedDict, total=False):
    id: str
    rights_holder_name: str
    asset_kind: str
    reference_fingerprint: str
    policy_mode: str
    claimed_segment_seconds: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    content_item_id: str
    reference_file_id: str
    match_confidence: float
    source: str
    status: str
    claim_level: str
    lock_reason: str
    revenue_locked: bool
    taken_down_at: Optional[str]
    dispute_deadline_at: Optional[str]
    appeal_attempts: int
    appeal_count: int
    copyright_counter_notified: bool
    created_at: str
    updated_at: str
    version: int


class CopyrightStrike(TypedDict, total=False):
    id: str
    channel_id: str
    content_item_id: str
    claim_id: str
    strike_sequence: int
    status: str
    acknowledged: bool
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class ChannelStrike(TypedDict, total=False):
    id: str
    channel_id: str
    kind: str
    reason_code: str
    status: str
    issued_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class MembershipSchedule(TypedDict, total=False):
    id: str
    channel_id: str
    tier_name: str
    monthly_fee_cents: int
    perks: List[str]
    creator_share_cents: int
    platform_share_cents: int
    network_fee_cents: int
    member_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class ChannelMembership(TypedDict, total=False):
    id: str
    channel_id: str
    member_name: str
    monthly_fee_cents: int
    joined_at: str
    paid_member_months: int
    status: str
    payout_cents: int
    created_at: str
    updated_at: str
    version: int


class PayoutBatch(TypedDict, total=False):
    id: str
    channel_id: str
    route_batch_id: Optional[str]
    stage: str
    status: str
    period_start_at: str
    period_end_at: str
    gross_cents: int
    creator_share_cents: int
    partner_share_cents: int
    held_cents: int
    tax_withheld_cents: int
    withholding_rate_pct: float
    adjusted_net_cents: int
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Append-only sub-resources (no updated_at, no version) ───

class AdReview(TypedDict, total=False):
    id: str
    content_item_id: str
    outcome: str
    reason_codes: List[str]
    matched_categories: List[str]
    like_count: int
    comment_count: int
    appeal_outcome: str
    is_visible: bool
    created_at: str


class ClaimDispute(TypedDict, total=False):
    id: str
    claim_id: str
    reason_code: str
    narrative: str
    status: str
    created_at: str


class ClaimAppeal(TypedDict, total=False):
    id: str
    claim_id: str
    appeal_level: str
    grounds_code: str
    status: str
    created_at: str


class RevenueRouting(TypedDict, total=False):
    id: str
    content_item_id: str
    claim_id: Optional[str]
    stream_type: str
    gross_revenue_cents: int
    matched_segment_seconds: int
    creator_share_cents: int
    partner_share_cents: int
    status: str
    created_at: str


class RevenueEvent(TypedDict, total=False):
    id: str
    channel_id: str
    stream_type: str
    content_item_id: Optional[str]
    amount_cents: int
    occurred_at: str
    routed: bool