"""Domain types: entity TypedDicts, status enums and the role enumeration.

Field names mirror the PRD exactly. Entities that carry the full four-field
system property set (`id`, `created_at`, `updated_at`, `version`) are declared
with all four; `Region` and `EngagementEvent` are deliberately lighter and
carry only `id` and `created_at`.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class PublisherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TitleStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    RETIRED = "RETIRED"


class TierCode(str, Enum):
    ESSENTIAL = "ESSENTIAL"
    PREMIUM = "PREMIUM"
    ULTIMATE = "ULTIMATE"


class CompensationModel(str, Enum):
    FIXED = "FIXED"
    ENGAGEMENT = "ENGAGEMENT"
    HYBRID = "HYBRID"


class DealStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    LIVE = "LIVE"
    EXPIRING = "EXPIRING"
    COMPLETED = "COMPLETED"


class ReleaseClass(str, Enum):
    DAY_ONE = "DAY_ONE"
    BACK_CATALOG = "BACK_CATALOG"
    CATALOG_ADD = "CATALOG_ADD"


class EntryStatus(str, Enum):
    PLANNED = "PLANNED"
    ADDED = "ADDED"
    REMOVING = "REMOVING"
    DELISTED = "DELISTED"


class MaintenanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class BillingPeriod(str, Enum):
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"


class BillingStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"


class LifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    CANCELLED = "CANCELLED"


class EntitlementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    REVOKED = "REVOKED"


class AccessChannel(str, Enum):
    CONSOLE = "CONSOLE"
    PC = "PC"
    CLOUD = "CLOUD"
    ONLINE_PLAY = "ONLINE_PLAY"


class PurchaseStatus(str, Enum):
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"


class Decision(str, Enum):
    APPROVE_DAY_ONE = "APPROVE_DAY_ONE"
    HOLD_FOR_CATALOG = "HOLD_FOR_CATALOG"
    REJECT_DAY_ONE = "REJECT_DAY_ONE"


class ProjectionStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class CapacityStatus(str, Enum):
    WITHIN_CAPACITY = "WITHIN_CAPACITY"
    OVER_CAPACITY = "OVER_CAPACITY"


class UserRole(str, Enum):
    CATALOG_ADMIN = "CatalogAdmin"
    CATALOG_ANALYST = "CatalogAnalyst"
    SUBSCRIBER = "Subscriber"
    ANONYMOUS = "Anonymous"


# Aliases matching the error catalogue's role spelling
CatalogAdmin = "CatalogAdmin"
CatalogAnalyst = "CatalogAnalyst"
SubscriberRole = "Subscriber"
AnonymousRole = "Anonymous"


# ---------------------------------------------------------------------------
# Entities carrying the full system property set
# ---------------------------------------------------------------------------

class Publisher(TypedDict):
    id: str
    name: str
    home_region_code: str
    status: str
    deal_count: int
    lifetime_licensing_cost_cents: float
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict):
    id: str
    publisher_id: str
    name: str
    platform_set: List[str]
    day_one_eligible: bool
    list_price_cents: float
    unit_sales_30d: int
    weighted_engagement_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionTier(TypedDict):
    id: str
    tier_code: str
    monthly_price_cents: float
    console_access: bool
    pc_access: bool
    cloud_access: bool
    online_play_bundle: bool
    member_discount_pct: float
    discount_retention_days: int
    annual_prepay_credit_ratio: float
    current_subscriber_count: int
    created_at: str
    updated_at: str
    version: int


class LicensingDeal(TypedDict):
    id: str
    publisher_id: str
    title_id: str
    compensation_model: str
    monthly_fixed_fee_cents: int
    guaranteed_compensation_cents: int
    engagement_rate_cents_per_hour: float
    monthly_engagement_cap_cents: int
    compensation_floor_cents: float
    payable_compensation_cents: float
    term_start_date: str
    term_end_date: str
    status: str
    signed_at: Optional[str]
    add_effective_date: str
    removal_effective_date: Optional[str]
    entry_id: Optional[str]
    maintenances_in_window: int
    created_at: str
    updated_at: str
    version: int


class CatalogEntry(TypedDict):
    id: str
    title_id: str
    deal_id: str
    region_code: str
    tiers: List[str]
    announced_add_date: str
    actual_add_date: Optional[str]
    removal_date: str
    release_class: str
    popularity_index_cents: int
    popularity_index_cents_30d_avg: int
    removal_notice_days: int
    subscriber_impact_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CatalogMaintenance(TypedDict):
    id: str
    region_code: str
    maintenance_start: str
    maintenance_end: str
    capacity_reduction_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict):
    id: str
    email: str
    display_name: str
    home_region_code: str
    status: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    subscriber_id: str
    tier_code: str
    billing_period: str
    prepay_amount_cents: float
    unpaid_months: int
    monthly_bill_cents: float
    monthly_engaged_hours_avg: float
    engagement_score: float
    billing_status: str
    lifecycle_status: str
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Entitlement(TypedDict):
    id: str
    subscription_id: str
    title_id: str
    region_code: str
    entry_id: Optional[str]
    access_channels: List[str]
    status: str
    retained_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Purchase(TypedDict):
    id: str
    subscriber_id: str
    title_id: str
    entry_id: str
    quantity: int
    region_code: str
    list_price_cents_per_unit: float
    discount_pct_applied: float
    wallet_applied_cents: int
    wallet_restored_cents: int
    unit_sales_credit_cents: float
    total_charged_cents: float
    status: str
    created_at: str
    updated_at: str
    version: int


class AvailabilityProjection(TypedDict):
    id: str
    title_id: str
    region_code: str
    release_class: str
    launch_subscriber_count: int
    tier_step_count: int
    projected_unit_sales_units: int
    projected_subscription_value_cents: float
    projected_cannibalized_unit_sales_cents: float
    projected_net_value_cents: float
    decision: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Entities created with only id + created_at
# ---------------------------------------------------------------------------

class Region(TypedDict):
    """Region is declared with only id and created_at: no updated_at, no version."""
    id: str
    region_code: str
    currency_code: str
    price_multiplier: float
    availability_ceiling_titles: int
    catalog_tier_floor: str
    capacity_required_slots: float
    capacity_usable_slots: float
    capacity_deficit_slots: float
    capacity_utilization_pct: float
    capacity_status: str
    created_at: str


class EngagementEvent(TypedDict):
    """EngagementEvent is append-only: only id and created_at."""
    id: str
    subscription_id: str
    title_id: str
    session_hours: float
    channel: str
    engagement_multiplier: float
    normalized_hours: float
    created_at: str


# Request payload TypedDicts (union-friendly for parametrized tests)
Payload = dict