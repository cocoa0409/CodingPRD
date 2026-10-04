"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, List, TypedDict


class Sport(str, Enum):
    NFL = "NFL"
    NBA = "NBA"
    MLB = "MLB"
    SOCCER = "SOCCER"
    GOLF = "GOLF"
    RACING = "RACING"
    TENNIS = "TENNIS"


class PropertyStatus(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class AmortizationMethod(str, Enum):
    STRAIGHT_LINE = "STRAIGHT_LINE"
    EVENT_WEIGHTED = "EVENT_WEIGHTED"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    COMPLETE = "COMPLETE"
    REPLACED = "REPLACED"
    CANCELLED = "CANCELLED"


class RightsMode(str, Enum):
    SIMULCAST = "SIMULCAST"
    EXCLUSIVE = "EXCLUSIVE"


class RuleKind(str, Enum):
    BLACKOUT = "BLACKOUT"
    OVERFLOW = "OVERFLOW"


class RuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class SubscriptionTier(str, Enum):
    FREE = "FREE"
    AD_SUPPORTED = "AD_SUPPORTED"
    PREMIUM = "PREMIUM"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class AcquisitionSource(str, Enum):
    ORGANIC = "ORGANIC"
    PARTNER_BUNDLE = "PARTNER_BUNDLE"


class GrantType(str, Enum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"


class ScopeKind(str, Enum):
    REGION = "REGION"
    EVENT = "EVENT"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    BOOKED = "BOOKED"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class SlotScope(str, Enum):
    NATIONAL = "NATIONAL"
    LOCAL = "LOCAL"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    RESERVED = "RESERVED"
    FILLED = "FILLED"
    UNFILLABLE = "UNFILLABLE"
    CANCELLED = "CANCELLED"


class FillSource(str, Enum):
    NATIONAL = "NATIONAL"
    LOCAL_INSERTION = "LOCAL_INSERTION"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class BundledTier(str, Enum):
    AD_SUPPORTED = "AD_SUPPORTED"
    PREMIUM = "PREMIUM"


class CodeStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class SourceType(str, Enum):
    SUBSCRIPTION = "SUBSCRIPTION"
    PARTNER_BUNDLE = "PARTNER_BUNDLE"


class ReplayAssetStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    EXPIRED = "EXPIRED"
    PULLED = "PULLED"


class UserRole(str, Enum):
    RIGHTS_MANAGER = "RightsManager"
    AD_OPS = "AdOps"
    STREAM_OPS = "StreamOps"
    PARTNER_MANAGER = "PartnerManager"
    VIEWER = "Viewer"


# --- Entity TypedDicts ---
# Entities carrying updated_at + version (PRD §2.4 common fields).


class RightsProperty(TypedDict, total=False):
    id: str
    property_code: str
    display_name: str
    sport: str
    status: str
    rights_fee_cents: int
    term_start: str
    term_end: str
    amortization_method: str
    simulcast_windows_count: int
    exclusive_windows_count: int
    simulcast_windows_consumed: int
    exclusive_windows_consumed: int
    minimum_exclusive_ratio_pct: int
    required_local_breaks_per_event: int
    amortized_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class StreamingWindow(TypedDict, total=False):
    id: str
    property_id: str
    event_code: str
    rights_mode: str
    status: str
    scheduled_start: str
    scheduled_end: str
    live_start: Optional[str]
    territory_scope: List[str]
    regional_block: bool
    is_marquee: bool
    capacity_required_units: int
    replay_hours: int
    replaced_by_id: Optional[str]
    supersedes_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TerritoryRule(TypedDict, total=False):
    id: str
    window_id: str
    region_code: str
    rule_kind: str
    rule_status: str
    effective_start: str
    effective_end: str
    broadcast_obligation_ref: str
    created_at: str
    updated_at: str
    version: int


class Viewer(TypedDict, total=False):
    id: str
    email: str
    home_region: str
    subscription_tier: str
    subscription_status: str
    acquisition_source: Optional[str]
    acquisition_window_id: Optional[str]
    marquee_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class CapacityPool(TypedDict, total=False):
    id: str
    pool_code: str
    scope_kind: str
    region_code: Optional[str]
    window_id: Optional[str]
    total_units: int
    committed_units: int
    oversubscribe_pct: int
    created_at: str
    updated_at: str
    version: int


class CapacityReservation(TypedDict, total=False):
    id: str
    pool_id: str
    window_id: str
    units: int
    status: str
    hold_expires_at: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdCampaign(TypedDict, total=False):
    id: str
    advertiser_code: str
    campaign_status: str
    flight_start: str
    flight_end: str
    frequency_cap_per_viewer: int
    frequency_window_hours: int
    cpm_cents: int
    region_target: List[str]
    created_at: str
    updated_at: str
    version: int


class AdSlot(TypedDict, total=False):
    id: str
    window_id: str
    break_index: int
    pod_index: int
    duration_seconds: int
    slot_scope: str
    region_code: Optional[str]
    booked_campaign_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionPartner(TypedDict, total=False):
    id: str
    partner_code: str
    display_name: str
    partner_status: str
    bundled_tier: str
    max_promo_codes: int
    codes_issued: int
    created_at: str
    updated_at: str
    version: int


class PromoCode(TypedDict, total=False):
    id: str
    partner_id: str
    code: str
    code_status: str
    issued_at: str
    expires_at: str
    redeemed_by_viewer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReplayAsset(TypedDict, total=False):
    id: str
    window_id: str
    status: str
    available_from: str
    expires_at: str
    replay_views: int
    created_at: str
    updated_at: str
    version: int


# Append-only entities (PRD §2.4): only id + created_at, no updated_at/version.


class ViewGrant(TypedDict, total=False):
    id: str
    viewer_id: str
    window_id: str
    grant_type: str
    region: str
    issued_at: str
    revoked: bool
    created_at: str


class Impression(TypedDict, total=False):
    id: str
    campaign_id: str
    viewer_id: str
    slot_id: str
    served_at: str
    revenue_cents: int
    fill_source: str
    created_at: str


class Entitlement(TypedDict, total=False):
    id: str
    viewer_id: str
    source_type: str
    partner_id: Optional[str]
    tier_granted: str
    active_from: str
    active: bool
    created_at: str
