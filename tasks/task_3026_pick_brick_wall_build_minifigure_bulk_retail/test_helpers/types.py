"""Domain types: entity shapes, status enums and the role enum."""
from enum import Enum
from typing import Optional, TypedDict


class StoreStage(str, Enum):
    TRADING = "TRADING"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class MemberStage(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class MemberTier(str, Enum):
    STANDARD = "STANDARD"
    VIP = "VIP"


class ElementStatus(str, Enum):
    PENDING_CATALOG = "PENDING_CATALOG"
    ACTIVE = "ACTIVE"
    RETIRED_TO_ARCHIVE = "RETIRED_TO_ARCHIVE"
    CATALOG = "CATALOG"


class SourcingMode(str, Enum):
    SURPLUS = "SURPLUS"
    CURRENT_PRODUCTION = "CURRENT_PRODUCTION"


class ThemeLaunchStage(str, Enum):
    SCHEDULED = "SCHEDULED"
    VIP_EARLY = "VIP_EARLY"
    STAGED_OPEN = "STAGED_OPEN"
    CLOSED = "CLOSED"


class LaunchQueueStatus(str, Enum):
    WAITING = "WAITING"
    GRANTED = "GRANTED"
    PURCHASED = "PURCHASED"
    NO_SHOW = "NO_SHOW"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"
    PURCHASED_ROLLBACK = "PURCHASED_ROLLBACK"


class IdentityCheckState(str, Enum):
    IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"
    IDENTITY_VERIFIED = "IDENTITY_VERIFIED"
    IDENTITY_ESCALATED = "IDENTITY_ESCALATED"


class WallBinStatus(str, Enum):
    OPEN = "OPEN"
    LOW = "LOW"
    EMPTY = "EMPTY"
    RETIRED = "RETIRED"


class FusionOrderStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    VOID = "VOID"
    CLOSED = "CLOSED"


class CupSize(str, Enum):
    SMALL = "SMALL"
    LARGE = "LARGE"
    JUMBO = "JUMBO"


class PricingModel(str, Enum):
    CUP_FILL = "CUP_FILL"
    PER_PIECE = "PER_PIECE"


class BuildStatus(str, Enum):
    BUILDING = "BUILDING"
    SEALED = "SEALED"
    RETURNED = "RETURNED"


class EventKind(str, Enum):
    BUILD_EVENT = "BUILD_EVENT"
    MINI_BUILD = "MINI_BUILD"


class EventStage(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    COMPLETED = "COMPLETED"


class ReservationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WAITLISTED = "WAITLISTED"
    PROMOTED = "PROMOTED"
    PASSED = "PASSED"
    EXPIRED = "EXPIRED"
    NOT_ADMITTED = "NOT_ADMITTED"


class ReplacementStage(str, Enum):
    OPEN = "OPEN"
    PROSPECT = "PROSPECT"
    DENIED = "DENIED"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"


class InspectionStage(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"


class LedgerEntryKind(str, Enum):
    REDEMPTION = "REDEMPTION"
    REPLACEMENT_GRANT = "REPLACEMENT_GRANT"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STORE_ASSOCIATE = "StoreAssociate"
    MEMBER = "Member"


# ─── Entity shapes ────────────────────────────────────
# Every primary resource carries id + created_at + updated_at + version.

class Store(TypedDict):
    id: str
    store_code: str
    display_name: str
    wall_bin_capacity_grams: int
    bin_engine_mass_grams: int
    shrinkage_basis_points: int
    event_capacity_units: int
    checklist_required: bool
    last_event_run_index: int
    stage: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    display_name: str
    tier: str
    home_store_id: str
    passed_mb_reservations: int
    points_balance: int
    stage: str
    created_at: str
    updated_at: str
    version: int


class Element(TypedDict):
    id: str
    element_code: str
    element_name: str
    theme: str
    unit_mass_grams: float
    cost_basis_cents: int
    make_ready_lead_days: int
    sourcing_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ThemeLaunch(TypedDict):
    id: str
    theme: str
    release_utc: str
    vip_early_access_utc: str
    per_customer_limit: int
    exclusive_set_sku: str
    exclusive_set_unit_price_cents: int
    allocated_exclusive_units: int
    exclusive_set_units_remaining: int
    soft_hold_units: int
    stage: str
    created_at: str
    updated_at: str
    version: int


class LaunchQueue(TypedDict):
    id: str
    store_id: str
    member_id: str
    launch_id: str
    priority_class: str
    requested_units: int
    sequence: int
    wait_mark: int
    status: str
    granted_units: int
    id_check_state: str
    batch_index: int
    soft_hold_units: int
    created_at: str
    updated_at: str
    version: int


class WallBin(TypedDict):
    id: str
    store_id: str
    element_id: str
    bin_label: str
    bin_capacity_grams: int
    bin_mass_grams: int
    fill_pct: float
    depletion_rate_pct_per_day: float
    status: str
    last_restock_index: int
    created_at: str
    updated_at: str
    version: int


class FusionOrder(TypedDict):
    id: str
    store_id: str
    member_id: str
    cup_size: str
    pricing_model: str
    pieced_element_id: Optional[str]
    declared_piece_count: int
    declared_mass_grams: int
    measured_volume_ml: float
    priced_piece_count: int
    base_price_cents: int
    member_discount_cents: int
    final_price_cents: int
    variance_grams: int
    status: str
    exit_inspection_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only: id + created_at only.
class FusionAllocation(TypedDict):
    id: str
    fusion_order_id: str
    wall_bin_id: str
    allocation_grams: int
    created_at: str


class MinifigureBuild(TypedDict):
    id: str
    store_id: str
    member_id: str
    torso_element_id: Optional[str]
    head_element_id: Optional[str]
    legs_element_id: Optional[str]
    accessory_element_id: Optional[str]
    platform_gen: int
    components_missing: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StoreEvent(TypedDict):
    id: str
    store_id: str
    event_kind: str
    title: str
    capacity_units: int
    start_utc: str
    end_utc: str
    registered_count: int
    waitlisted_count: int
    waitlist_epoch: int
    event_run_index: int
    stage: str
    created_at: str
    updated_at: str
    version: int


class MiniBuildReservation(TypedDict):
    id: str
    store_event_id: str
    member_id: str
    seats: int
    wait_mark: int
    status: str
    arrival_counter: int
    checked_in_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReplacementRequest(TypedDict):
    id: str
    store_id: str
    member_id: str
    element_id: str
    quantity_missing: int
    proof_of_purchase_supplied: bool
    window_days: int
    window_expires_utc: str
    earned_points: int
    stage: str
    created_at: str
    updated_at: str
    version: int


# Append-only: id + created_at only.
class LoyaltyLedger(TypedDict):
    id: str
    member_id: str
    entry_kind: str
    points_delta: int
    reason: str
    created_at: str


class ExitInspection(TypedDict):
    id: str
    fusion_order_id: str
    outcome: str
    checklist_result: str
    reviewed_by_user_id: str
    variance_bps: int
    stage: str
    created_at: str
    updated_at: str
    version: int