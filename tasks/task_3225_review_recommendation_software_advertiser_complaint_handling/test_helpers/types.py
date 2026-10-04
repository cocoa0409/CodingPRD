"""Domain types: entity TypedDicts, status enums, role enum.

Entities with versioned lifecycle carry id + created_at + updated_at + version.
The three advertising event resources are append-only: id + created_at only.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_OPS = "PlatformOps"
    REVIEWER = "Reviewer"
    BUSINESS_OWNER = "BusinessOwner"
    ADVERTISER = "Advertiser"
    CONTENT_MODERATOR = "ContentModerator"
    TRUST_INVESTIGATOR = "TrustInvestigator"
    SUPPORT_ADMIN = "SupportAdmin"
    LEGAL_OPS = "LegalOps"
    REPORTER = "Reporter"


class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    PURGED = "PURGED"


class BusinessPageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    MERGED = "MERGED"


class RecommendationState(str, Enum):
    PENDING = "PENDING"
    DISPLAYED = "DISPLAYED"
    FILTERED = "FILTERED"
    REMOVED = "REMOVED"


class PageClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PageClaimKind(str, Enum):
    CLAIM = "CLAIM"
    TRANSFER = "TRANSFER"


class AdAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AdCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AdCampaignKind(str, Enum):
    SPONSORED_PLACEMENT = "SPONSORED_PLACEMENT"
    CALL_TRACKING = "CALL_TRACKING"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    ESCALATED = "ESCALATED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_ACTIONED = "RESOLVED_ACTIONED"
    REJECTED = "REJECTED"


class ComplaintKind(str, Enum):
    FILTERED_DISPUTE = "FILTERED_DISPUTE"
    NEGATIVE_DISPUTE = "NEGATIVE_DISPUTE"
    SOLICITATION_REPORT = "SOLICITATION_REPORT"


class ComplaintAction(str, Enum):
    UPHOLD_FILTER = "UPHOLD_FILTER"
    RESTORE_REVIEW = "RESTORE_REVIEW"
    REMOVE_REVIEW = "REMOVE_REVIEW"


class SolicitationCaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class ConsumerAlertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class ConsumerAlertKind(str, Enum):
    SOLICITATION_EVIDENCE = "SOLICITATION_EVIDENCE"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"
    MEDIA_ATTENTION = "MEDIA_ATTENTION"


class IdentityRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NOTICE_SENT = "NOTICE_SENT"
    RELEASED = "RELEASED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class IdentityChannel(str, Enum):
    MEDIA = "MEDIA"
    LEGAL_SUBPOENA = "LEGAL_SUBPOENA"
    LAW_ENFORCEMENT = "LAW_ENFORCEMENT"


class MergeRequestStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"


class ReportVariant(str, Enum):
    STRICT = "STRICT"
    EXTENDED = "EXTENDED"


class User(TypedDict, total=False):
    id: str
    email: str
    display_name: str
    home_region: str
    trust_score: int
    strike_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BusinessPage(TypedDict, total=False):
    id: str
    name: str
    address_line: str
    city: str
    category: str
    website: str
    claimed_by_user_id: Optional[str]
    merged_into_id: Optional[str]
    displayed_review_count: int
    displayed_rating_avg_x100: int
    ad_account_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict, total=False):
    id: str
    page_id: str
    author_user_id: str
    rating: int
    text: str
    submitted_at: str
    edited_flag: bool
    evidence_confirmed: bool
    recommendation_state: str
    recommendation_score_x1000: int
    created_at: str
    updated_at: str
    version: int


class PageClaim(TypedDict, total=False):
    id: str
    page_id: str
    claimant_user_id: str
    kind: str
    evidence_text: str
    verification_code: str
    decided_by_admin_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdAccount(TypedDict, total=False):
    id: str
    page_id: str
    owner_user_id: str
    daily_budget_cents: int
    spent_today_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdCampaign(TypedDict, total=False):
    id: str
    ad_account_id: str
    kind: str
    bid_cents: int
    starts_on: str
    ends_on: str
    call_tracking_enabled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (common_fields: false): NO updated_at, NO version.
class AdImpressionEvent(TypedDict, total=False):
    id: str
    ad_account_id: str
    campaign_id: str
    idempotency_key: str
    cost_cents: int
    served_on: str
    created_at: str


class CallTrackEvent(TypedDict, total=False):
    id: str
    ad_account_id: str
    campaign_id: str
    caller_number: str
    called_at: str
    duration_seconds: int
    qualified: bool
    cost_cents: int
    attribution_window_days: int
    created_at: str


class AttributionReport(TypedDict, total=False):
    id: str
    ad_account_id: str
    campaign_id: str
    period_start: str
    period_end: str
    variant: str
    impressions: int
    qualified_calls: int
    spend_cents: int
    created_at: str


class Complaint(TypedDict, total=False):
    id: str
    page_id: str
    review_id: str
    filer_user_id: str
    kind: str
    body: str
    escalated: bool
    decided_by_admin_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SolicitationCase(TypedDict, total=False):
    id: str
    page_id: str
    reporter_user_id: str
    target_review_ids: List[str]
    evidence_text: str
    confirmed_review_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsumerAlert(TypedDict, total=False):
    id: str
    page_id: str
    kind: str
    case_id: Optional[str]
    evidence_text: str
    review_cooldown_until: str
    lifted_by_admin_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IdentityRequest(TypedDict, total=False):
    id: str
    subject_user_id: str
    requester_label: str
    channel: str
    legal_process_ref: Optional[str]
    notice_sent_at: Optional[str]
    notice_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MergeRequest(TypedDict, total=False):
    id: str
    duplicate_page_id: str
    survivor_page_id: str
    reason: str
    decided_by_admin_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
