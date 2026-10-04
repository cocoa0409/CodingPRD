"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


class Posture(str, Enum):
    OFFSEASON = "OFFSEASON"
    WINTER_HEATING = "WINTER_HEATING"
    SPRING_PLANTING = "SPRING_PLANTING"
    FALL_FEED = "FALL_FEED"


class CampaignSeason(str, Enum):
    WINTER_HEATING = "WINTER_HEATING"
    SPRING_PLANTING = "SPRING_PLANTING"
    FALL_FEED = "FALL_FEED"


class SeasonCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    TEARDOWN = "TEARDOWN"
    VERIFY_PENDING = "VERIFY_PENDING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StagingBayStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class SizeClass(str, Enum):
    M = "M"
    L = "L"
    XL = "XL"


class HatcheryScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class LivestockLotStatus(str, Enum):
    RECEIVING = "RECEIVING"
    ON_SALE = "ON_SALE"
    SUSPENDED = "SUSPENDED"
    SALE_CLOSED = "SALE_CLOSED"
    DISPOSITIONED = "DISPOSITIONED"


class HealthFlag(str, Enum):
    NORMAL = "NORMAL"
    QUARANTINED = "QUARANTINED"


class CareLogEntryType(str, Enum):
    FEEDING = "FEEDING"
    WATER = "WATER"
    TEMPERATURE = "TEMPERATURE"
    MORTALITY = "MORTALITY"


class ChickOrderStatus(str, Enum):
    RESERVED = "RESERVED"
    BROODER_VERIFIED = "BROODER_VERIFIED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    NONE = "NONE"
    CLAIMED = "CLAIMED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SaleKind(str, Enum):
    FEED_BULK = "FEED_BULK"
    PROPANE_EXCHANGE = "PROPANE_EXCHANGE"


class ContainerClass(str, Enum):
    BAG_50 = "BAG_50"
    DRUM = "DRUM"
    TOTE = "TOTE"
    CYLINDER_20 = "CYLINDER_20"


class WeightedSaleStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class LoyaltyAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class LoyaltyTier(str, Enum):
    NEIGHBOR = "NEIGHBOR"
    RANCH_HAND = "RANCH_HAND"
    HOMESTEAD = "HOMESTEAD"


class LedgerEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    REDEMPTION = "REDEMPTION"
    ADJUSTMENT = "ADJUSTMENT"
    REVERSAL = "REVERSAL"


class EarnContext(str, Enum):
    FEED = "FEED"
    FUEL = "FUEL"
    OTHER = "OTHER"


class FulfillmentStatus(str, Enum):
    PLACED = "PLACED"
    STAGED = "STAGED"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class LoadoutStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    ASSISTANCE_REQUESTED = "ASSISTANCE_REQUESTED"
    LOADOUT_DONE = "LOADOUT_DONE"


class ServiceEventKind(str, Enum):
    PET_WASH = "PET_WASH"
    VET_CLINIC = "VET_CLINIC"


class ServiceEventStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    REGIONAL_ADMIN = "RegionalAdmin"
    STORE_MANAGER = "StoreManager"
    STORE_ASSOCIATE = "StoreAssociate"
    CUSTOMER = "Customer"
    ANONYMOUS = "Anonymous"


# ---- Entity TypedDicts -------------------------------------------------------
# Entities with common fields carry id + created_at + updated_at + version.
# CareLogEntry and LoyaltyLedgerEntry are append-only logs and carry only
# id + created_at.


class Store(TypedDict, total=False):
    id: str
    store_name: str
    region_code: str
    posture: str
    active_campaign_id: Optional[str]
    hazmat_gallons_used_today: float
    created_at: str
    updated_at: str
    version: int


class SeasonCampaign(TypedDict, total=False):
    id: str
    store_id: str
    season: str
    planogram_map: str
    aisle_count: int
    aisles_reset_count: int
    activated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StagingBay(TypedDict, total=False):
    id: str
    store_id: str
    bay_no: int
    size_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HatcherySchedule(TypedDict, total=False):
    id: str
    store_id: str
    species: str
    breed: str
    hatch_date: str
    sale_window_start: str
    sale_window_end: str
    daily_capacity: int
    min_purchase_qty: int
    base_price_cents_per_bird: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LivestockLot(TypedDict, total=False):
    id: str
    store_id: str
    hatchery_schedule_id: str
    quantity_received: int
    received_at: str
    quantity_on_hand: int
    quantity_sold: int
    mortality_count: int
    quantity_quarantined: int
    mortality_rate: float
    health_flag: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CareLogEntry(TypedDict, total=False):
    # append-only: id + created_at only, no updated_at / version
    id: str
    lot_id: str
    entry_type: str
    measured_temp_f: Optional[float]
    mortality_count: Optional[int]
    note: Optional[str]
    created_at: str


class ChickOrder(TypedDict, total=False):
    id: str
    store_id: str
    livestock_lot_id: str
    loyalty_account_id: str
    quantity: int
    pickup_date: str
    unit_price_cents: int
    discount_pct: float
    total_cents: int
    brooder_verified_at: Optional[str]
    fulfilled_at: Optional[str]
    claim_status: str
    claimed_mortality_count: int
    approved_claim_count: int
    refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WeightedSale(TypedDict, total=False):
    id: str
    store_id: str
    loyalty_account_id: Optional[str]
    sale_kind: str
    container_class: str
    gross_weight_lbs: float
    provisional_tare_lbs: float
    measured_tare_lbs: Optional[float]
    provisional_total_cents: int
    final_total_cents: Optional[int]
    propane_gallons: float
    points_redeemed: int
    finalized_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LoyaltyAccount(TypedDict, total=False):
    id: str
    full_name: str
    phone: str
    email: Optional[str]
    status: str
    tier: str
    points_balance: int
    tier_qualifying_points: int
    created_at: str
    updated_at: str
    version: int


class LoyaltyLedgerEntry(TypedDict, total=False):
    # append-only: id + created_at only, no updated_at / version
    id: str
    account_id: str
    entry_type: str
    store_id: Optional[str]
    base_amount_cents: Optional[int]
    earn_context: Optional[str]
    points_delta: int
    related_entry_id: Optional[str]
    counts_toward_tier: bool
    posture_at_entry: str
    created_at: str


class PickupOrder(TypedDict, total=False):
    id: str
    store_id: str
    loyalty_account_id: str
    item_sku: str
    item_size_class: str
    requires_loadout_assistance: bool
    staging_bay_id: Optional[str]
    ready_at: Optional[str]
    pickup_deadline: Optional[str]
    fulfillment_status: str
    loadout_status: str
    created_at: str
    updated_at: str
    version: int


class ServiceEvent(TypedDict, total=False):
    id: str
    store_id: str
    event_kind: str
    resource_name: str
    event_date: str
    slot_window_start: str
    slot_window_end: str
    slot_length_minutes: int
    cleanup_buffer_minutes: int
    capacity_per_slot: int
    requires_vaccine_record: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EventBooking(TypedDict, total=False):
    id: str
    service_event_id: str
    loyalty_account_id: str
    slot_start: str
    slot_end: str
    vaccine_record_confirmed: bool
    status: str
    created_at: str
    updated_at: str
    version: int
