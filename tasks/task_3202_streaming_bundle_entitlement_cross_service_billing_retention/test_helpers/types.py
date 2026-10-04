"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Optional, TypedDict


class PlanKind(str, Enum):
    STANDALONE = "STANDALONE"
    BUNDLE = "BUNDLE"


class Service(str, Enum):
    DPLUS = "DPLUS"
    HULU = "HULU"


class AdTier(str, Enum):
    AD_SUPPORTED = "AD_SUPPORTED"
    AD_FREE = "AD_FREE"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ProfileStatus(str, Enum):
    LINKED = "LINKED"
    SUSPENDED = "SUSPENDED"
    UNLINKED = "UNLINKED"


class MaturityRating(str, Enum):
    TV_Y = "TV_Y"
    TV_G = "TV_G"
    TV_PG = "TV_PG"
    TV_14 = "TV_14"
    TV_MA = "TV_MA"


class BillerType(str, Enum):
    PLATFORM = "PLATFORM"
    APP_STORE = "APP_STORE"
    DISTRIBUTOR = "DISTRIBUTOR"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    HARD_FAILED = "HARD_FAILED"


class LifecycleStatus(str, Enum):
    PENDING_ENTITLEMENT = "PENDING_ENTITLEMENT"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCEL_SCHEDULED = "CANCEL_SCHEDULED"
    CANCELLED = "CANCELLED"
    MIGRATED_OUT = "MIGRATED_OUT"


class BillingDimension(str, Enum):
    PAID_UP = "PAID_UP"
    GRACE = "GRACE"
    UNPAID = "UNPAID"


class EntitlementStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class MigrationStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class ProrationMethod(str, Enum):
    CHRONOLOGICAL_REMAINING = "CHRONOLOGICAL_REMAINING"
    FORWARD_LOOKING_PERIOD = "FORWARD_LOOKING_PERIOD"


class OfferStatus(str, Enum):
    OPEN = "OPEN"
    RETIRED = "RETIRED"


class RedemptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


class InvoiceKind(str, Enum):
    INITIAL = "INITIAL"
    RENEWAL = "RENEWAL"
    MIGRATION_ADJUSTMENT = "MIGRATION_ADJUSTMENT"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    SUBSCRIBER = "Subscriber"
    SUPPORT = "Support"
    DISTRIBUTOR_OPS = "DistributorOps"
    PLATFORM_ADMIN = "PlatformAdmin"


# Config-style entities (common_fields: false) — carry ONLY id + created_at.
class Plan(TypedDict, total=False):
    id: str
    created_at: str
    plan_code: str
    plan_kind: str
    service_scope: list
    ad_tier: str
    monthly_price_cents: int
    component_weights: Optional[dict]
    allow_app_store_billing: bool
    allow_distributor_billing: bool
    is_legacy: bool


class RetentionOffer(TypedDict, total=False):
    id: str
    created_at: str
    offer_code: str
    discount_cents: int
    duration_months: int
    max_redemptions_per_account: int
    eligible_biller_types: list
    eligible_plan_kinds: list
    offer_status: str


class WatchlistItem(TypedDict, total=False):
    id: str
    created_at: str
    service_profile_id: str
    title_id: str
    title_maturity: str


class RevenueAllocation(TypedDict, total=False):
    id: str
    created_at: str
    invoice_id: str
    service: str
    allocated_cents: int


# Full-bookkeeping entities (common_fields: true) — id + created_at +
# updated_at + version.
class SubscriberAccount(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    email: str
    full_name: str
    account_status: str
    grandfathered_price_cents: Optional[int]
    grandfathered_plan_code: Optional[str]
    retention_redemption_count: int
    account_credit_cents: int


class ServiceProfile(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    subscriber_account_id: str
    service: str
    profile_status: str
    maturity_rating_cap: str
    kids_mode: bool
    watchlist_count: int


class BillingAccount(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    subscriber_account_id: str
    biller_type: str
    biller_reference: str
    billing_status: str
    period_start: Optional[str]
    period_end: Optional[str]
    consecutive_failure_count: int


class Subscription(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    subscriber_account_id: str
    billing_account_id: str
    plan_code: str
    lifecycle_status: str
    billing_dimension: str
    price_cents: int
    retention_discount_cents: int
    migration_id: Optional[str]
    pending_plan_code: Optional[str]
    cancel_effective_at: Optional[str]


class Entitlement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    subscription_id: str
    service_profile_id: str
    service: str
    entitlement_status: str
    mismatch_flag: bool


class Migration(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    subscriber_account_id: str
    from_subscription_id: str
    to_subscription_id: Optional[str]
    target_plan_code: str
    migration_status: str
    proration_credit_cents: int
    proration_method_used: str


class RetentionRedemption(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    subscription_id: str
    subscriber_account_id: str
    offer_code: str
    redemption_status: str
    months_remaining: int


class Invoice(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    billing_account_id: str
    subscription_id: str
    invoice_status: str
    invoice_kind: str
    gross_cents: int
    credit_applied_cents: int
    net_cents: int
    period_start: str
    period_end: str
