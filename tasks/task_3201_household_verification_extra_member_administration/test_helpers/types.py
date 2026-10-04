"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class RegionCode(str, Enum):
    NA = "NA"
    LATAM = "LATAM"
    EMEA = "EMEA"
    APAC = "APAC"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class VerificationPosture(str, Enum):
    VERIFIED = "VERIFIED"
    CHALLENGE_PENDING = "CHALLENGE_PENDING"
    LOCKED = "LOCKED"


class HouseholdStatus(str, Enum):
    ESTABLISHED = "ESTABLISHED"
    RELOCATING = "RELOCATING"
    DISSOLVED = "DISSOLVED"


class MemberRole(str, Enum):
    OWNER = "OWNER"
    HOUSEHOLD = "HOUSEHOLD"
    EXTRA = "EXTRA"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class DeviceType(str, Enum):
    TV = "TV"
    MOBILE = "MOBILE"
    WEB = "WEB"
    CONSOLE = "CONSOLE"


class TrustStatus(str, Enum):
    UNTRUSTED = "UNTRUSTED"
    TRUSTED = "TRUSTED"
    REMOVED = "REMOVED"


class SlotStatus(str, Enum):
    OFFERED = "OFFERED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    LAPSED = "LAPSED"


class TransferRights(str, Enum):
    TRANSFERABLE = "TRANSFERABLE"
    LOCKED = "LOCKED"


class ChallengeChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    VOICE_CALL = "VOICE_CALL"


class ChallengeReason(str, Enum):
    NEW_DEVICE = "NEW_DEVICE"
    PERIODIC = "PERIODIC"
    LOCATION_DRIFT = "LOCATION_DRIFT"


class ChallengeStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    LOCKED_OUT = "LOCKED_OUT"


class TravelPassGrantType(str, Enum):
    TEMPORARY_14D = "TEMPORARY_14D"
    TEMPORARY_30D = "TEMPORARY_30D"


class TravelPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    CONVERTED = "CONVERTED"


class TransferStatus(str, Enum):
    AWAITING_ACCEPTANCE = "AWAITING_ACCEPTANCE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class Resolution(str, Enum):
    SD = "SD"
    HD = "HD"
    UHD = "UHD"


class SessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class DownloadStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MessagingVariant(str, Enum):
    SOFT = "SOFT"
    HARD = "HARD"


class MetricType(str, Enum):
    CHURN_SIGNAL = "CHURN_SIGNAL"
    COMPLAINT = "COMPLAINT"
    WINBACK = "WINBACK"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SUPPORT_AGENT = "SupportAgent"
    ACCOUNT_OWNER = "AccountOwner"
    HOUSEHOLD_MEMBER = "HouseholdMember"
    EXTRA_MEMBER = "ExtraMember"


class Account(TypedDict, total=False):
    id: str
    email: str
    region_code: str
    plan_tier: str
    status: str
    verification_posture: str
    billing_anchor_day: int
    owner_member_id: str
    extra_member_billed_cents: int
    extra_member_credit_cents: int
    extra_member_net_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict, total=False):
    id: str
    account_id: str
    label: str
    primary_location: str
    network_fingerprint: str
    geo_cell: str
    status: str
    trusted_device_count: int
    last_verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    account_id: str
    display_name: str
    member_role: str
    status: str
    viewing_history: list
    recommendation_seed: str
    current_streams: int
    downloads_used_this_month: int
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    household_id: str
    device_label: str
    device_type: str
    network_fingerprint: str
    geo_cell: str
    trust_status: str
    last_signal_at: str
    travel_pass_active: bool
    created_at: str
    updated_at: str
    version: int


class ExtraMemberSlot(TypedDict, total=False):
    id: str
    account_id: str
    member_id: Optional[str]
    payer_member_id: str
    transfer_rights: str
    status: str
    slot_index: int
    price_cents_snapshot: int
    credit_cents: int
    purchased_day: int
    created_at: str
    updated_at: str
    version: int


class VerificationChallenge(TypedDict, total=False):
    id: str
    account_id: str
    channel: str
    challenge_reason: str
    code: str
    status: str
    attempts_used: int
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class TravelPass(TypedDict, total=False):
    id: str
    device_id: str
    grant_type: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProfileTransfer(TypedDict, total=False):
    id: str
    source_account_id: str
    member_id: str
    target_email: str
    status: str
    expires_at: str
    history_snapshot: list
    recommendation_snapshot: str
    target_account_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlaybackSession(TypedDict, total=False):
    id: str
    member_id: str
    device_id: str
    requested_resolution: str
    resolution_granted: str
    status: str
    started_at: str
    ended_at: Optional[str]
    created_at: str


class Download(TypedDict, total=False):
    id: str
    member_id: str
    device_id: str
    title_id: str
    status: str
    billing_month: str
    created_at: str


class EnforcementPolicy(TypedDict, total=False):
    id: str
    region_code: str
    enforcement_enabled: bool
    grace_days: int
    messaging_variant: str
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EnforcementMetric(TypedDict, total=False):
    id: str
    account_id: str
    metric_type: str
    notes: str
    recorded_at: str
    created_at: str
