"""Domain types for the satellite radio trial-conversion API.

TypedDicts mirror the PRD's entity surface. Entities with full lifecycle
carry id + created_at + updated_at + version; the append-only families
(OfferRedemption, BillingLedgerEntry, DisclosureRecord) carry only id and
created_at, per the PRD's resource-identity rule.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums (string values are case-sensitive and transmitted exactly as spelled)
# ---------------------------------------------------------------------------

class AutomakerStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DealerStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CustomerStatus:
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class VehicleCondition:
    NEW = "NEW"
    USED = "USED"


class HardwareGeneration:
    GEN1 = "GEN1"
    GEN2 = "GEN2"
    GEN3 = "GEN3"


class RadioActivationStatus:
    UNREGISTERED = "UNREGISTERED"
    REGISTERED = "REGISTERED"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class ServiceMode:
    IN_VEHICLE = "IN_VEHICLE"
    STREAMING_ONLY = "STREAMING_ONLY"
    BUNDLED = "BUNDLED"


class TermKind:
    TRIAL = "TRIAL"
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"


class SubscriptionKind:
    TRIAL = "TRIAL"
    PAID = "PAID"
    SAVE_OFFER = "SAVE_OFFER"


class SubscriptionStatus:
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCEL_SCHEDULED = "CANCEL_SCHEDULED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    TRANSFERRED_AWAY = "TRANSFERRED_AWAY"


class SubscriptionOrigin:
    OEM_FEED = "OEM_FEED"
    USED_DEALER = "USED_DEALER"
    WEB_SIGNUP = "WEB_SIGNUP"
    CALL_CENTER = "CALL_CENTER"
    SAVE_ACCEPT = "SAVE_ACCEPT"
    TRANSFER_IN = "TRANSFER_IN"


class DisclosureState:
    NONE = "NONE"
    REQUIRED = "REQUIRED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class LifecyclePhase:
    IN_TRIAL = "IN_TRIAL"
    POST_TRIAL = "POST_TRIAL"
    WINBACK = "WINBACK"
    SAVE = "SAVE"


class CampaignState:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class CommandType:
    ACTIVATE = "ACTIVATE"
    DEACTIVATE = "DEACTIVATE"
    SUSPEND = "SUSPEND"
    RESUME = "RESUME"


class SignalPath:
    SATELLITE = "SATELLITE"
    CELLULAR = "CELLULAR"


class SignalStatus:
    QUEUED = "QUEUED"
    SENT = "SENT"
    ACKED = "ACKED"
    FAILED = "FAILED"
    EXHAUSTED = "EXHAUSTED"
    SUPERSEDED = "SUPERSEDED"


class LedgerEntryType:
    CHARGE = "CHARGE"
    PRORATION_CREDIT = "PRORATION_CREDIT"
    REFUND = "REFUND"
    SAVE_CREDIT = "SAVE_CREDIT"
    TRANSFER_ADJUSTMENT = "TRANSFER_ADJUSTMENT"


class DisclosureType:
    RENEWAL_NOTICE = "RENEWAL_NOTICE"
    SAVE_RENEWAL_NOTICE = "SAVE_RENEWAL_NOTICE"
    TRIAL_END_NOTICE = "TRIAL_END_NOTICE"


class DisclosureChannel:
    EMAIL = "EMAIL"
    POSTAL = "POSTAL"


class EffectiveMode:
    IMMEDIATE = "IMMEDIATE"
    END_OF_TERM = "END_OF_TERM"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Automaker(TypedDict, total=False):
    id: str
    oem_code: str
    name: str
    feed_contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict, total=False):
    id: str
    dealer_code: str
    name: str
    used_program_enrolled: bool
    used_program_enrolled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    status: str
    household_size: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    vin: str
    automaker_id: str
    model_year: int
    owner_customer_id: str
    condition: str
    created_at: str
    updated_at: str
    version: int


class Radio(TypedDict, total=False):
    id: str
    esn: str
    vehicle_id: str
    hardware_generation: str
    activation_status: str
    last_signal_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackageTier(TypedDict, total=False):
    id: str
    code: str
    name: str
    channel_entitlements: List[str]
    includes_streaming: bool
    min_hardware_generation: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionPlan(TypedDict, total=False):
    id: str
    code: str
    name: str
    package_tier_id: str
    service_mode: str
    is_trial: bool
    term_kind: str
    term_length_days: int
    price_cents: int
    auto_renew_default: bool
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    customer_id: str
    radio_id: Optional[str]
    plan_id: str
    kind: str
    status: str
    origin: str
    start_at: str
    end_at: str
    auto_renew: bool
    is_primary_for_discount: bool
    current_term_price_cents: int
    disclosure_state: str
    save_offers_used_in_term: int
    cancel_requested_at: Optional[str]
    supersession_seq: int
    created_at: str
    updated_at: str
    version: int


class OfferCampaign(TypedDict, total=False):
    id: str
    code: str
    name: str
    lifecycle_phase: str
    state: str
    window_start_at: str
    window_end_at: str
    created_at: str
    updated_at: str
    version: int


class OfferStep(TypedDict, total=False):
    id: str
    campaign_id: str
    step_index: int
    plan_id: str
    step_up_rank: int
    discount_pct_bps: int
    flat_discount_cents: int
    eligibility_expr: Dict[str, Any]
    max_redemptions_per_customer: int
    created_at: str
    updated_at: str
    version: int


# Append-only families: id + created_at only — no updated_at, no version.

class OfferRedemption(TypedDict, total=False):
    id: str
    campaign_id: str
    offer_step_id: str
    customer_id: str
    subscription_id: str
    redeemed_price_cents: int
    redeemed_at: str
    created_at: str


class SignalCommand(TypedDict, total=False):
    id: str
    radio_id: str
    subscription_id: str
    command_type: str
    path: str
    status: str
    attempt_count: int
    next_retry_at: Optional[str]
    idempotency_key: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingLedgerEntry(TypedDict, total=False):
    id: str
    subscription_id: str
    entry_type: str
    amount_cents: int
    effective_at: str
    idempotency_key: Optional[str]
    note: Optional[str]
    created_at: str


class DisclosureRecord(TypedDict, total=False):
    id: str
    subscription_id: str
    disclosure_type: str
    channel: str
    sent_at: str
    due_before: str
    acknowledged_at: Optional[str]
    created_at: str
