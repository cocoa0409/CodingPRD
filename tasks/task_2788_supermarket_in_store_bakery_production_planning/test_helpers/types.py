"""Domain types: status enums, role enum and entity TypedDicts.

Every resource in this system carries the same four system-managed properties
(PRD §2.4): ``id``, ``created_at``, ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    REGIONAL_ADMIN = "RegionalAdmin"
    DEPARTMENT_MANAGER = "DepartmentManager"
    BAKER = "Baker"
    DECORATOR = "Decorator"
    CAKE_DESK = "CakeDesk"


ALL_ROLES = [r.value for r in UserRole]


class PlanPosture(str, Enum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class MarkdownAuthorization(str, Enum):
    AUTO = "AUTO"
    MANAGER_ONLY = "MANAGER_ONLY"


class DayOfWeek(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class Daypart(str, Enum):
    MORNING = "MORNING"
    MIDDAY = "MIDDAY"
    EVENING = "EVENING"


class ProductionMethod(str, Enum):
    SCRATCH = "SCRATCH"
    PAR_BAKED = "PAR_BAKED"
    THAW_AND_SERVE = "THAW_AND_SERVE"


class AllergenCode(str, Enum):
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    MILK = "MILK"
    EGG = "EGG"
    SOY = "SOY"
    WHEAT = "WHEAT"
    SESAME = "SESAME"


class AllergenMode(str, Enum):
    SHARED = "SHARED"
    NUT_FREE_DEDICATED = "NUT_FREE_DEDICATED"


class OvenStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class ReplenishmentState(str, Enum):
    OK = "OK"
    REORDER_DUE = "REORDER_DUE"
    ON_ORDER = "ON_ORDER"


class RunExecutionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PROOFING = "PROOFING"
    BAKING = "BAKING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RunDispositionStatus(str, Enum):
    PENDING = "PENDING"
    ON_SHELF = "ON_SHELF"
    MARKED_DOWN = "MARKED_DOWN"
    CLEARED = "CLEARED"


class RunOrigin(str, Enum):
    PLAN_GENERATED = "PLAN_GENERATED"
    MANUAL = "MANUAL"


class CancelledReason(str, Enum):
    PLAN_SUPERSEDED = "PLAN_SUPERSEDED"
    DAY_CLOSED = "DAY_CLOSED"


class WasteRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class DispositionReason(str, Enum):
    DAY_OLD_UNSOLD = "DAY_OLD_UNSOLD"
    DONATED = "DONATED"
    DAMAGED = "DAMAGED"
    BURNT = "BURNT"
    OVERPRODUCTION = "OVERPRODUCTION"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DecorationComplexity(str, Enum):
    SIMPLE = "SIMPLE"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class CakeOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    CONFIRMED = "CONFIRMED"
    IN_DECORATION = "IN_DECORATION"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    EXPIRED = "EXPIRED"


class IngredientOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RECEIVED_FULL = "RECEIVED_FULL"
    RECEIVED_SHORT = "RECEIVED_SHORT"
    CANCELLED = "CANCELLED"


class IngredientOrderOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO_REORDER = "AUTO_REORDER"


# --- Entity shapes ----------------------------------------------------------
# All ten resources carry id / created_at / updated_at / version (PRD §2.4).


class BakeryDepartment(TypedDict):
    id: str
    name: str
    store_number: str
    shrink_budget_pct: float
    labor_rate_cents_per_minute: float
    freight_surcharge_pct: float
    donation_partner_enabled: bool
    open_purchase_commitment_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    department_id: str
    sku: str
    name: str
    production_method: str
    units_per_rack: int
    proof_minutes: int
    bake_minutes: int
    cool_minutes: int
    base_labor_minutes_per_rack: float
    setup_labor_minutes: float
    unit_retail_cents: int
    shelf_life_hours: int
    markdown_pct: float
    allergen_tags: List[str]
    allergen_free_claim: bool
    is_custom_cake_base: bool
    recipe_lines: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class Ingredient(TypedDict):
    id: str
    department_id: str
    name: str
    case_pack_units: int
    unit_cost_cents: float
    shelf_life_days: int
    daily_usage_units: int
    reorder_point_units: int
    on_hand_units: int
    allergen_tags: List[str]
    replenishment_state: str
    created_at: str
    updated_at: str
    version: int


class Oven(TypedDict):
    id: str
    department_id: str
    name: str
    deck_count: int
    rack_capacity_per_deck: int
    changeover_buffer_minutes: int
    allergen_mode: str
    oven_status: str
    status_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BakeDay(TypedDict):
    id: str
    department_id: str
    business_date: str
    day_of_week: str
    labor_budget_minutes: int
    oven_shift_start_utc: str
    oven_shift_end_utc: str
    plan_posture: str
    markdown_authorization: str
    forecast_lines: List[Dict[str, Any]]
    planned_labor_minutes: float
    planned_units_total: int
    plan_unmet_unit_count: int
    actual_labor_minutes: float
    produced_units_total: int
    production_cost_cents: int
    waste_units_total: int
    shrink_cost_cents: int
    shrink_cost_basis_pct: float
    shrink_unit_basis_pct: float
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    bake_day_id: str
    product_id: str
    oven_id: Optional[str]
    deck_index: Optional[int]
    origin: str
    rack_count: int
    planned_units: int
    planned_labor_minutes: float
    ingredient_cost_cents: int
    proof_start_utc: Optional[str]
    bake_start_utc: Optional[str]
    bake_end_utc: Optional[str]
    ready_utc: Optional[str]
    expires_utc: Optional[str]
    execution_status: str
    disposition_status: str
    cancelled_reason: Optional[str]
    actual_units: Optional[int]
    final_labor_minutes: Optional[float]
    unit_cost_basis_cents: Optional[int]
    wasted_units_total: int
    on_shelf_units: int
    markdown_unit_price_cents: Optional[int]
    executed_by_user_id: Optional[str]
    shared_equipment_label_tags: List[str]
    created_at: str
    updated_at: str
    version: int


class WasteRecord(TypedDict):
    id: str
    bake_day_id: str
    production_run_id: str
    disposition_reason: str
    units: int
    unit_cost_basis_cents: int
    waste_cost_cents: int
    record_status: str
    attested_by_user_id: str
    voided_by_user_id: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PickupSlot(TypedDict):
    id: str
    bake_day_id: str
    slot_start_utc: str
    slot_end_utc: str
    decorator_capacity_units: int
    reserved_decoration_units: int
    slot_status: str
    created_at: str
    updated_at: str
    version: int


class CustomCakeOrder(TypedDict):
    id: str
    bake_day_id: str
    pickup_slot_id: str
    product_id: str
    customer_name: str
    decoration_complexity: str
    tier_count: int
    allergen_free_required: bool
    rush_requested: bool
    decoration_units: int
    required_decoration_lead_minutes: int
    decoration_deadline_utc: str
    quote_subtotal_cents: int
    rush_fee_cents: int
    volume_discount_cents: int
    quote_total_cents: int
    order_status: str
    revision_count: int
    decoration_started_utc: Optional[str]
    ready_at_utc: Optional[str]
    picked_up_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IngredientOrder(TypedDict):
    id: str
    department_id: str
    target_bake_day_id: Optional[str]
    origin: str
    order_status: str
    lines: List[Dict[str, Any]]
    order_total_cents: int
    shortfall_units_total: Optional[int]
    submitted_at_utc: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
