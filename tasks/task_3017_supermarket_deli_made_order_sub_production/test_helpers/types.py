"""Domain types for the Deli & Made-to-Order Sub Production API.

Every entity in this API declares the common field set (`id`, `created_at`,
`updated_at`, `version`), so each TypedDict below carries all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class StorePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    HALT = "HALT"


class PostureReason(str, Enum):
    OK = "OK"
    INVENTORY_TRIGGERED = "INVENTORY_TRIGGERED"
    REVOCATION_TRIGGERED = "REVOCATION_TRIGGERED"
    NO_ACTIVE_PRICE_FILE = "NO_ACTIVE_PRICE_FILE"
    CERTIFICATION_TRIGGERED = "CERTIFICATION_TRIGGERED"
    POSTURE_GATE_TRIGGERED = "POSTURE_GATE_TRIGGERED"


class ItemCategory(str, Enum):
    HOT_BAR = "HOT_BAR"
    COLD_CUT = "COLD_CUT"
    ROTISSERIE = "ROTISSERIE"
    SUB = "SUB"
    BREAD = "BREAD"
    CATERING_PLATTER = "CATERING_PLATTER"


class ItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ProductionStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PRODUCTION = "IN_PRODUCTION"
    ON_LINE = "ON_LINE"


class HoldStatus(str, Enum):
    HOLDING = "HOLDING"
    MARKED_DOWN = "MARKED_DOWN"
    DISCARDED = "DISCARDED"


class SanitationStatus(str, Enum):
    CLEAN = "CLEAN"
    IN_USE = "IN_USE"
    NEEDS_SANITATION = "NEEDS_SANITATION"
    SANITIZING = "SANITIZING"


class SlicerCycleType(str, Enum):
    ROUTINE = "ROUTINE"
    ALLERGEN_CHANGEOVER = "ALLERGEN_CHANGEOVER"
    TIMED = "TIMED"


class SlicerCycleStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    ABORTED = "ABORTED"


class TicketFulfillmentStatus(str, Enum):
    QUEUED = "QUEUED"
    TICKETED = "TICKETED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    PICKED_UP = "PICKED_UP"
    REMADE = "REMADE"
    ABANDONED = "ABANDONED"


class TicketBreadStatus(str, Enum):
    QUEUED = "QUEUED"
    BREAD_HOLD = "BREAD_HOLD"


class OrderChannel(str, Enum):
    IN_STORE = "IN_STORE"
    DIGITAL = "DIGITAL"
    PHONE = "PHONE"


class PromotionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class BreadOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    SHORT = "SHORT"
    RECONCILED = "RECONCILED"


class PriceFileStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class LabelSubjectType(str, Enum):
    SUB_TICKET = "SUB_TICKET"
    PRODUCTION_BATCH = "PRODUCTION_BATCH"
    CATERING_PLATTER = "CATERING_PLATTER"


class LabelStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class CateringStatus(str, Enum):
    INQUIRY = "INQUIRY"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class AssociateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PrimaryRole(str, Enum):
    DELI_CLERK = "DELI_CLERK"
    DELI_MANAGER = "DELI_MANAGER"
    BAKERY_COORDINATOR = "BAKERY_COORDINATOR"


class CertType(str, Enum):
    SLICER_OPERATION = "SLICER_OPERATION"
    FOOD_HANDLING = "FOOD_HANDLING"
    ALLERGEN_MANAGEMENT = "ALLERGEN_MANAGEMENT"


class CertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    RENEWED = "RENEWED"


class WasteReason(str, Enum):
    HOLD_EXPIRED = "HOLD_EXPIRED"
    TEMPERATURE_BREACH = "TEMPERATURE_BREACH"
    ALLERGEN_CONTAMINATION = "ALLERGEN_CONTAMINATION"
    QUALITY = "QUALITY"
    UNCLAIMED_PLATTER = "UNCLAIMED_PLATTER"


class WasteStatus(str, Enum):
    DRAFT = "DRAFT"
    MARKED_DOWN = "MARKED_DOWN"
    DISCARDED = "DISCARDED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DELI_MANAGER = "DeliManager"
    DELI_CLERK = "DeliClerk"
    BAKERY_COORDINATOR = "BakeryCoordinator"
    SCALE_OPERATOR = "ScaleOperator"


class Store(TypedDict, total=False):
    id: str
    store_number: str
    name: str
    deli_case_capacity_lbs: float
    hot_bar_capacity_lbs: float
    sub_station_count: int
    haccp_safety_flag: bool
    case_on_hand_lbs: float
    posture: str
    posture_gate_flag: bool
    posture_reason: str
    certified_slicer_operator_count: int
    active_price_file_id: Optional[str]
    targeted_promo_id: Optional[str]
    covered_allergen_set: List[str]
    available_bread_units: int
    verified_waste_liability_cents: int
    pending_waste_verification_count: int
    ops_run_index: int
    logical_clock_at_last_run: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliItem(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    unit_cost_cents: int
    retail_price_per_lb_cents: int
    case_life_minutes: int
    markdown_window_minutes: int
    allergen_flags: List[str]
    slicer_required: bool
    servings_per_platter: int
    bread_deli_item_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionBatch(TypedDict, total=False):
    id: str
    store_id: str
    deli_item_id: str
    slicer_id: Optional[str]
    produced_by_associate_id: str
    rework_of_batch_id: Optional[str]
    batch_code: str
    planned_lbs: float
    produced_lbs: float
    produced_at: Optional[str]
    hold_expires_at: Optional[str]
    production_status: str
    hold_status: str
    markdown_sold_lbs: float
    markdown_cents: int
    discard_lbs: float
    temperature_breach: bool
    case_yield_cost_provisional_cents: Optional[int]
    case_yield_cost_final_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SlicerAsset(TypedDict, total=False):
    id: str
    store_id: str
    assigned_deli_item_id: Optional[str]
    last_sliced_deli_item_id: Optional[str]
    assigned_operator_id: Optional[str]
    asset_tag: str
    sanitation_cycle_limit: int
    sanitation_status: str
    cuts_since_sanitation: int
    in_use_minutes: int
    last_sanitized_at: Optional[str]
    open_sanitation_cycle_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SanitationCycle(TypedDict, total=False):
    id: str
    store_id: str
    slicer_id: str
    production_batch_id: Optional[str]
    allergen_cleared_from_item_id: Optional[str]
    verified_by_associate_id: Optional[str]
    cycle_type: str
    cycle_minutes: int
    buffer_minutes: int
    started_at: str
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SubTicket(TypedDict, total=False):
    id: str
    store_id: str
    deli_item_id: str
    bread_deli_item_id: str
    order_channel: str
    placed_by_customer_ref: Optional[str]
    lines: List[dict]
    creation_sequence: int
    ticket_number: int
    queue_position: int
    weight_lbs: float
    status: str
    promised_at: Optional[str]
    completed_at: Optional[str]
    line_total_cents: Optional[int]
    lateness_minutes: int
    remake_count: int
    label_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict, total=False):
    id: str
    promo_code: str
    deli_item_id: str
    week_start_date: str
    week_end_date: str
    forecast_uplift_pct: float
    trailing_baseline_units: int
    required_bread_units: int
    settled_bread_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BreadSupplyOrder(TypedDict, total=False):
    id: str
    store_id: str
    bread_deli_item_id: str
    promotion_id: str
    committed_units: int
    required_units: int
    delivered_units: int
    shortfall_units: int
    reserved_units: int
    unreserved_required_units: int
    submit_by_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScalePriceFile(TypedDict, total=False):
    id: str
    store_id: str
    file_label: str
    effective_from: str
    effective_to: str
    item_price_count: int
    status: str
    activated_at: Optional[str]
    synced_scale_count: int
    created_at: str
    updated_at: str
    version: int


class Label(TypedDict, total=False):
    id: str
    store_id: str
    sub_ticket_id: Optional[str]
    price_file_id: Optional[str]
    subject_type: str
    subject_ref_id: str
    net_weight_lbs: float
    unit_price_cents: int
    total_price_cents: int
    printed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CateringOrder(TypedDict, total=False):
    id: str
    store_id: str
    platter_deli_item_id: str
    parent_order_id: Optional[str]
    certified_planner_associate_id: str
    customer_name: str
    platter_count: int
    headcount: int
    lead_time_hours: int
    pickup_window_start: str
    pickup_window_end: str
    deposit_cents: int
    quote_total_cents: int
    pickup_bucket_key: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Associate(TypedDict, total=False):
    id: str
    store_id: str
    employee_number: str
    full_name: str
    primary_role: str
    status: str
    allergy_set: List[str]
    active_certification_count: int
    assigned_slicer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    store_id: str
    associate_id: str
    deli_item_id: Optional[str]
    revoked_by_manager_id: Optional[str]
    cert_type: str
    issued_at: str
    expires_at: str
    status: str
    grace_reminder: bool
    created_at: str
    updated_at: str
    version: int


class WasteRecord(TypedDict, total=False):
    id: str
    store_id: str
    production_batch_id: str
    markdown_by_associate_id: str
    verifier_associate_id: Optional[str]
    verified_by_certification_id: Optional[str]
    discard_lbs: float
    reason: str
    markdown_sold_lbs: float
    markdown_cents: int
    markdown_recorded_at: Optional[str]
    discarded_at: Optional[str]
    discard_value_cents: Optional[int]
    handling_fee_cents: Optional[int]
    total_liability_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PostureReport(TypedDict, total=False):
    store_id: str
    posture: str
    posture_reason: str
    protection_index: int
    diffusion_index: int
    newest_completed_ticket_lateness_minutes: int
    certified_slicer_operator_count: int
    case_on_hand_lbs: float


class SubQueue(TypedDict, total=False):
    store_id: str
    queue_depth: int
    ordered_total_count: int
    ordered: List[dict]