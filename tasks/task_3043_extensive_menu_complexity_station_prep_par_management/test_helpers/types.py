"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    MENU_ADMIN = "MenuAdmin"
    KITCHEN_MANAGER = "KitchenManager"
    PREP_COOK = "PrepCook"
    LINE_COOK = "LineCook"
    PASTRY_CHEF = "PastryChef"
    INVENTORY_CONTROLLER = "InventoryController"


class StationType(str, Enum):
    GRILL = "GRILL"
    SAUTE = "SAUTE"
    FRY = "FRY"
    BAKERY = "BAKERY"
    COLD = "COLD"


class RestaurantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MenuRevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ModificationPolicy(str, Enum):
    ALLOWED = "ALLOWED"
    LIMITED = "LIMITED"
    FORBIDDEN = "FORBIDDEN"


class PrepItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BatchUnit(str, Enum):
    OZ = "OZ"
    EA = "EA"
    ML = "ML"


class ParHealth(str, Enum):
    OK = "OK"
    BELOW_PAR = "BELOW_PAR"
    CRITICAL = "CRITICAL"


class ParAdjustmentStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class StationParStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CookStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETRAINING_REQUIRED = "RETRAINING_REQUIRED"
    INACTIVE = "INACTIVE"


class ForecastStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"


class PrepListStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    LOCKED = "LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class GenerationVariant(str, Enum):
    OPTIMISTIC = "OPTIMISTIC"
    CONSERVATIVE = "CONSERVATIVE"


class PrepBatchStatus(str, Enum):
    PLANNED = "PLANNED"
    PREPPED = "PREPPED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    WASTED = "WASTED"
    CANCELLED = "CANCELLED"


class ShiftAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class CheesecakeType(str, Enum):
    ORIGINAL = "ORIGINAL"
    CHOCOLATE = "CHOCOLATE"
    STRAWBERRY = "STRAWBERRY"
    SEASONAL = "SEASONAL"


class BakeryOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class WasteReason(str, Enum):
    OVER_PREP = "OVER_PREP"
    EXPIRED = "EXPIRED"
    QUALITY = "QUALITY"
    SPILLAGE = "SPILLAGE"


class WasteEntryStatus(str, Enum):
    RECORDED = "RECORDED"
    ATTRIBUTED = "ATTRIBUTED"


class AllergenReviewStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    CLEARED = "CLEARED"


class FireStatus(str, Enum):
    OPEN = "OPEN"
    FIRED = "FIRED"
    READY = "READY"
    SERVED = "SERVED"
    VOIDED = "VOIDED"


class Restaurant(TypedDict, total=False):
    id: str
    name: str
    code: str
    weekly_bakery_budget_cents: int
    weekly_bakery_budget_spent_cents: int
    current_waitlist_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuRevision(TypedDict, total=False):
    id: str
    restaurant_id: str
    label: str
    effective_from: str
    review_cycle_count: int
    retraining_required_count: int
    recipe_card_redistribution_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Recipe(TypedDict, total=False):
    id: str
    menu_revision_id: str
    name: str
    station_type: str
    allergen_tags: List[str]
    modification_policy: str
    components: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class PrepItem(TypedDict, total=False):
    id: str
    name: str
    station_type: str
    shelf_life_hours: int
    min_batch_size: int
    batch_unit: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict, total=False):
    id: str
    restaurant_id: str
    name: str
    station_type: str
    rack_slot_capacity: int
    mise_en_place_layout: List[str]
    par_health: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class StationPar(TypedDict, total=False):
    id: str
    station_id: str
    prep_item_id: str
    par_quantity: int
    proposed_par_quantity: Optional[int]
    requested_by_cook_id: Optional[str]
    approved_by_cook_id: Optional[str]
    adjustment_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Cook(TypedDict, total=False):
    id: str
    restaurant_id: str
    name: str
    certified_station_types: List[str]
    certification_menu_revision_id: Optional[str]
    weekly_scheduled_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DemandForecast(TypedDict, total=False):
    id: str
    restaurant_id: str
    service_date: str
    expected_covers: int
    item_mix: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class PrepList(TypedDict, total=False):
    id: str
    restaurant_id: str
    demand_forecast_id: str
    generation_variant: Optional[str]
    lines: List[dict]
    total_rounded_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PrepBatch(TypedDict, total=False):
    id: str
    prep_list_id: str
    prep_item_id: str
    station_id: str
    quantity: int
    consumed_quantity: int
    wasted_quantity: int
    produced_at: Optional[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict, total=False):
    id: str
    cook_id: str
    station_id: str
    shift_start: str
    shift_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BakeryOrder(TypedDict, total=False):
    id: str
    restaurant_id: str
    cheesecake_type: str
    whole_cakes_ordered: int
    whole_cakes_received: Optional[int]
    provisional_slices: Optional[int]
    final_slice_count: Optional[int]
    yield_variance: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class WasteEntry(TypedDict, total=False):
    id: str
    station_id: str
    prep_batch_id: str
    quantity: int
    reason: str
    recorded_by_cook_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict, total=False):
    id: str
    restaurant_id: str
    table_ref: str
    items: List[dict]
    allergen_review_status: str
    fire_status: str
    recall_count: int
    created_at: str
    updated_at: str
    version: int
