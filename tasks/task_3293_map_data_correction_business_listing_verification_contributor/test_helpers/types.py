"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class RegionPosture(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARANCE_PENDING = "CLEARANCE_PENDING"
    CLEAR = "CLEAR"
    FROZEN = "FROZEN"


class ContributorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    BANNED = "BANNED"


class ContributorLevel(str, Enum):
    NEWCOMER = "NEWCOMER"
    REGULAR = "REGULAR"
    TRUSTED = "TRUSTED"
    EXPERT = "EXPERT"
    MASTER = "MASTER"


class GrantSourceType(str, Enum):
    EDIT = "EDIT"
    PHOTO = "PHOTO"
    REVIEW = "REVIEW"
    VERIFICATION_ASSIST = "VERIFICATION_ASSIST"
    ADJUSTMENT = "ADJUSTMENT"


class GrantStatus(str, Enum):
    POSTED = "POSTED"
    REVOKED = "REVOKED"


class ListingStatus(str, Enum):
    UNCLAIMED = "UNCLAIMED"
    CLAIM_PENDING = "CLAIM_PENDING"
    VERIFIED = "VERIFIED"
    REVERIFY_REQUIRED = "REVERIFY_REQUIRED"
    SUSPENDED = "SUSPENDED"
    PERMANENTLY_CLOSED = "PERMANENTLY_CLOSED"


class ListingVisibility(str, Enum):
    PUBLIC = "PUBLIC"
    RESTRICTED = "RESTRICTED"
    HIDDEN = "HIDDEN"


class ListingCategory(str, Enum):
    RESTAURANT = "RESTAURANT"
    RETAIL = "RETAIL"
    SERVICE = "SERVICE"
    LODGING = "LODGING"
    HEALTH = "HEALTH"


class VerificationMethod(str, Enum):
    POSTCARD = "POSTCARD"
    PHONE = "PHONE"
    VIDEO = "VIDEO"
    RECORDS = "RECORDS"


class VerificationStatus(str, Enum):
    ISSUED = "ISSUED"
    CODE_SUBMITTED = "CODE_SUBMITTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class VerificationFailureReason(str, Enum):
    WRONG_CODE = "WRONG_CODE"
    ATTEMPTS_EXHAUSTED = "ATTEMPTS_EXHAUSTED"
    MISMATCHED_RECORDS = "MISMATCHED_RECORDS"
    VIDEO_INSUFFICIENT = "VIDEO_INSUFFICIENT"


class EditType(str, Enum):
    NAME = "NAME"
    CATEGORY = "CATEGORY"
    ADDRESS = "ADDRESS"
    HOURS = "HOURS"
    LOCATION = "LOCATION"
    ATTRIBUTE = "ATTRIBUTE"


class EditStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AUTO_VALIDATED = "AUTO_VALIDATED"
    QUEUED = "QUEUED"
    IN_REVIEW = "IN_REVIEW"
    NEEDS_MORE_INFO = "NEEDS_MORE_INFO"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    REVERTED = "REVERTED"


class EditRejectionReason(str, Enum):
    AUTO_LOW_SCORE = "AUTO_LOW_SCORE"
    POLICY = "POLICY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    DUPLICATE = "DUPLICATE"


class TicketQueue(str, Enum):
    EDIT_REVIEW = "EDIT_REVIEW"
    REVIEW_MODERATION = "REVIEW_MODERATION"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    CLAIMED = "CLAIMED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class TicketPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TicketResolution(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    NEEDS_INFO = "NEEDS_INFO"
    REMOVE = "REMOVE"
    RESTORE = "RESTORE"
    DISMISS = "DISMISS"


class ReviewStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    FLAGGED = "FLAGGED"
    UNDER_MODERATION = "UNDER_MODERATION"
    REMOVED = "REMOVED"


class FlagReason(str, Enum):
    FAKE = "FAKE"
    CONFLICT_OF_INTEREST = "CONFLICT_OF_INTEREST"
    OFF_TOPIC = "OFF_TOPIC"
    HATE = "HATE"
    SPAM = "SPAM"


class FlagStatus(str, Enum):
    OPEN = "OPEN"
    DISMISSED = "DISMISSED"
    UPHELD = "UPHELD"


class ViolationType(str, Enum):
    KEYWORD_STUFFING = "KEYWORD_STUFFING"
    FAKE_ADDRESS = "FAKE_ADDRESS"
    PROHIBITED_CATEGORY = "PROHIBITED_CATEGORY"
    FAKE_REVIEWS = "FAKE_REVIEWS"
    IMPERSONATION = "IMPERSONATION"


class SuspensionCaseStatus(str, Enum):
    OPEN = "OPEN"
    APPEAL_SUBMITTED = "APPEAL_SUBMITTED"
    UNDER_APPEAL_REVIEW = "UNDER_APPEAL_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class HoursSource(str, Enum):
    OWNER = "OWNER"
    CONTRIBUTOR = "CONTRIBUTOR"
    WEB_CRAWL = "WEB_CRAWL"
    IMAGERY = "IMAGERY"
    THIRD_PARTY_FEED = "THIRD_PARTY_FEED"


class ImageryStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    CAPTURED = "CAPTURED"
    BLUR_PENDING = "BLUR_PENDING"
    REPROCESS = "REPROCESS"
    BLURRED = "BLURRED"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class BlurObligation(str, Enum):
    FACES_ONLY = "FACES_ONLY"
    FACES_AND_PLATES = "FACES_AND_PLATES"
    FULL_PRIVACY = "FULL_PRIVACY"


class RoutingKind(str, Enum):
    CLOSURE = "CLOSURE"
    CONSTRUCTION = "CONSTRUCTION"
    TURN_RESTRICTION = "TURN_RESTRICTION"


class RoutingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CONTRIBUTOR = "Contributor"
    BUSINESS_OWNER = "BusinessOwner"
    MODERATOR = "Moderator"
    POLICY_ANALYST = "PolicyAnalyst"
    IMAGERY_OPERATOR = "ImageryOperator"
    ROUTING_ENGINEER = "RoutingEngineer"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Entity TypedDicts ---


class Region(TypedDict, total=False):
    id: str
    name: str
    country_code: str
    timezone: str
    geo_min_lat: float
    geo_max_lat: float
    geo_min_lng: float
    geo_max_lng: float
    posture: str
    privacy_pending_count: int
    routing_version: int
    max_active_imagery_tasks: int
    created_at: str
    updated_at: str
    version: int


class Contributor(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    home_region_id: str
    status: str
    total_points: int
    lifetime_points: int
    level: str
    provisional_trust_score: int
    finalized_trust_score: int
    failed_verification_count: int
    created_at: str
    updated_at: str
    version: int


class ContributorGrant(TypedDict, total=False):
    # Append-only record: carries only id + created_at (no updated_at/version).
    id: str
    contributor_id: str
    source_type: str
    source_id: str
    base_points: int
    quality_multiplier: float
    points: int
    status: str
    note: str
    created_at: str


class BusinessListing(TypedDict, total=False):
    id: str
    region_id: str
    name: str
    category: str
    address_text: str
    geo_lat: float
    geo_lng: float
    owner_contributor_id: Optional[str]
    status: str
    visibility: str
    health_score: float
    moderation_health_score: float
    review_count: int
    rating_avg: float
    accepted_edit_count: int
    keyword_stuffing_strikes: int
    verification_method: Optional[str]
    verified_at: Optional[str]
    reverify_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VerificationAttempt(TypedDict, total=False):
    id: str
    listing_id: str
    method: str
    status: str
    code: str
    attempts_used: int
    max_attempts: int
    issued_at: str
    expires_at: str
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MapEdit(TypedDict, total=False):
    id: str
    listing_id: str
    contributor_id: str
    edit_type: str
    payload: dict
    status: str
    auto_score: float
    quality_weight: float
    rejection_reason: Optional[str]
    review_ticket_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewTicket(TypedDict, total=False):
    id: str
    map_edit_id: Optional[str]
    review_flag_id: Optional[str]
    queue: str
    status: str
    claimed_by: Optional[str]
    priority: str
    resolution: Optional[str]
    sla_due_at: str
    created_at: str
    updated_at: str
    version: int


class UserReview(TypedDict, total=False):
    id: str
    listing_id: str
    contributor_id: str
    rating: int
    text: str
    status: str
    fake_probability: float
    flag_count: int
    created_at: str
    updated_at: str
    version: int


class ReviewFlag(TypedDict, total=False):
    # Append-only record: carries only id + created_at (no updated_at/version).
    id: str
    review_id: str
    reporter_contributor_id: Optional[str]
    reporter_is_owner: bool
    reason: str
    status: str
    created_at: str


class SuspensionCase(TypedDict, total=False):
    id: str
    listing_id: str
    violation_type: str
    status: str
    evidence_notes: str
    appeal_text: Optional[str]
    appeal_deadline: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HoursObservation(TypedDict, total=False):
    # Append-only record: carries only id + created_at (no updated_at/version).
    id: str
    listing_id: str
    source: str
    day_mask: str
    open_time: str
    close_time: str
    recorded_at: str
    corroboration_count: int
    accepted: bool
    created_at: str


class ImageryTask(TypedDict, total=False):
    id: str
    region_id: str
    collection_zone: str
    operator_id: str
    status: str
    window_start: str
    window_end: str
    blur_obligation: str
    capture_media_count: int
    blurred_media_count: int
    created_at: str
    updated_at: str
    version: int


class RoutingUpdate(TypedDict, total=False):
    id: str
    region_id: str
    segment_ref: str
    kind: str
    status: str
    effective_start: str
    effective_end: str
    restriction_detail: Optional[dict]
    supersedes_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
