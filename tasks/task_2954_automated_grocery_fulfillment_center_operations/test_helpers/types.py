"""Domain types for the Automated Grocery Fulfillment Center Operations API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Every persisted resource in this service carries the same four
common properties (``id``, ``created_at``, ``updated_at``, ``version``), so
every TypedDict below lists all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Enumerations ────────────────────────────────────────────────────────────


class UserRole(str, Enum):
    """The five role names, spelled exactly as the PRD spells them."""

    FULFILLMENT_ADMIN = "FulfillmentAdmin"
    CUSTOMER = "Customer"
    WAVE_PLANNER = "WavePlanner"
    PICK_OPERATOR = "PickOperator"
    GRID_ENGINEER = "GridEngineer"


class TemperatureZone(str, Enum):
    """Cold-chain classes; ranked FROZEN, CHILLED, AMBIENT wherever ordering matters."""

    AMBIENT = "AMBIENT"
    CHILLED = "CHILLED"
    FROZEN = "FROZEN"


class GridZoneStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    MAINTENANCE = "MAINTENANCE"
    AUDIT_HOLD = "AUDIT_HOLD"


class PickStationStatus(str, Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"


class MaintenanceWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class LoyaltyTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class FulfillmentStatus(str, Enum):
    """The physical dimension of a customer order."""

    DRAFT = "DRAFT"
    SLOTTED = "SLOTTED"
    WAVED = "WAVED"
    PICKING = "PICKING"
    CONSOLIDATED = "CONSOLIDATED"
    LOADED = "LOADED"
    DISPATCHED = "DISPATCHED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    """The money dimension of a customer order."""

    PENDING_AUTH = "PENDING_AUTH"
    AUTHORIZED = "AUTHORIZED"
    ADJUSTED = "ADJUSTED"
    CAPTURED = "CAPTURED"
    REVERSED = "REVERSED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    PICKED = "PICKED"
    SHORT = "SHORT"
    CANCELLED = "CANCELLED"


class SubstitutionResolution(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    SUBSTITUTED = "SUBSTITUTED"
    SHORTAGE_ACCEPTED = "SHORTAGE_ACCEPTED"


class BookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    RELEASED = "RELEASED"
    BUMPED = "BUMPED"


class WaveStatus(str, Enum):
    FORMING = "FORMING"
    PICKING = "PICKING"
    CONSOLIDATED = "CONSOLIDATED"
    LOADING = "LOADING"
    DISPATCHED = "DISPATCHED"


class WavePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ToteStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    CONSOLIDATED = "CONSOLIDATED"
    LOADED = "LOADED"


class PickTaskStatus(str, Enum):
    QUEUED = "QUEUED"
    RETRIEVING = "RETRIEVING"
    COMPLETED = "COMPLETED"
    SHORT = "SHORT"
    CANCELLED = "CANCELLED"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


# ─── Entity shapes ───────────────────────────────────────────────────────────


class DeliveryRoute(TypedDict):
    id: str
    route_code: str
    service_area_name: str
    van_capacity_totes: int
    base_delivery_fee_cents: int
    per_km_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class DockBay(TypedDict):
    id: str
    bay_code: str
    parallel_van_capacity: int
    created_at: str
    updated_at: str
    version: int


class GridZone(TypedDict):
    id: str
    zone_code: str
    temperature_zone: str
    bot_count: int
    status: str
    accuracy_score_unit_weighted: Optional[float]
    accuracy_score_sku_weighted: Optional[float]
    last_audited_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PickStation(TypedDict):
    id: str
    station_code: str
    temperature_zone_capability: List[str]
    max_concurrent_totes: int
    current_tote_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventorySku(TypedDict):
    id: str
    sku_code: str
    name: str
    grid_zone_id: str
    temperature_zone: str
    substitution_group_code: str
    is_catchweight: bool
    unit_price_cents: int
    price_per_kg_cents: Optional[int]
    nominal_weight_grams: Optional[int]
    weight_tolerance_pct: Optional[float]
    physical_units: int
    allocated_units: int
    on_hand_units: int
    last_count_system_units: Optional[int]
    last_count_counted_units: Optional[int]
    last_count_variance_units: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict):
    id: str
    grid_zone_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliverySlot(TypedDict):
    id: str
    route_id: str
    window_start: str
    window_end: str
    total_capacity_units: int
    withheld_units: int
    held_units: int
    confirmed_units: int
    available_units: int
    surge_multiplier: float
    created_at: str
    updated_at: str
    version: int


class CustomerAccount(TypedDict):
    id: str
    email: str
    full_name: str
    loyalty_tier: str
    home_route_id: str
    created_at: str
    updated_at: str
    version: int


class CustomerOrder(TypedDict):
    id: str
    customer_id: str
    wave_id: Optional[str]
    stop_distance_km: float
    fulfillment_status: str
    billing_status: str
    merchandise_subtotal_cents: int
    delivery_fee_cents: Optional[int]
    loyalty_discount_cents: Optional[int]
    order_total_cents: Optional[int]
    authorized_amount_cents: Optional[int]
    captured_amount_cents: Optional[int]
    dispatch_blocked: bool
    open_substitution_count: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    sku_id: str
    ordered_qty: int
    nominal_weight_grams: Optional[int]
    line_status: str
    substitution_resolution: str
    provisional_line_price_cents: int
    final_line_price_cents: Optional[int]
    picked_units: Optional[int]
    picked_weight_grams: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SlotBooking(TypedDict):
    id: str
    delivery_slot_id: str
    customer_order_id: str
    units: int
    status: str
    quoted_fee_cents: int
    surge_multiplier_at_booking: float
    created_at: str
    updated_at: str
    version: int


class DeliveryWave(TypedDict):
    id: str
    route_id: str
    delivery_slot_id: str
    dock_bay_id: Optional[str]
    wave_code: str
    cutoff_at: str
    load_start: Optional[str]
    load_end: Optional[str]
    status: str
    posture: str
    order_count: int
    tote_count: int
    load_sequence: List[str]
    transport_cost_cents: Optional[int]
    consolidated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tote(TypedDict):
    id: str
    wave_id: str
    pick_station_id: str
    tote_code: str
    temperature_zone: str
    status: str
    assigned_line_count: int
    created_at: str
    updated_at: str
    version: int


class PickTask(TypedDict):
    id: str
    order_line_id: str
    sku_id: str
    grid_zone_id: str
    pick_station_id: str
    tote_id: Optional[str]
    sequence_index: int
    allocated_units: int
    picked_units: Optional[int]
    actual_weight_grams: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SubstitutionProposal(TypedDict):
    id: str
    order_line_id: str
    substitute_sku_id: str
    supersedes_proposal_id: Optional[str]
    round_no: int
    proposed_price_delta_cents: int
    status: str
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
