"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    SHIFT_MANAGER = "ShiftManager"
    LINE_OPERATOR = "LineOperator"
    PREP_COOK = "PrepCook"
    QUALITY_LEAD = "QualityLead"
    CUSTOMER = "Customer"


class AssemblyLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLEANING = "CLEANING"


class LinePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class LineType(str, Enum):
    AUTOMATED = "AUTOMATED"
    MANUAL = "MANUAL"


class IngredientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EIGHTY_SIXED = "EIGHTY_SIXED"


class StationType(str, Enum):
    BASE = "BASE"
    PROTEIN = "PROTEIN"
    TOPPING = "TOPPING"
    DRESSING = "DRESSING"


class HopperStatus(str, Enum):
    LOADING = "LOADING"
    IN_SERVICE = "IN_SERVICE"
    DEPLETED = "DEPLETED"
    REFILL_SCHEDULED = "REFILL_SCHEDULED"
    REFILLING = "REFILLING"
    QUARANTINED = "QUARANTINED"


class RefillTaskStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PrepBatchStatus(str, Enum):
    IN_PREP = "IN_PREP"
    READY = "READY"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSEMBLING = "ASSEMBLING"
    VERIFICATION = "VERIFICATION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderRoute(str, Enum):
    AUTOMATED = "AUTOMATED"
    MANUAL = "MANUAL"


class SubstitutionRuleStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


class SanitationCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class LaborRole(str, Enum):
    MAKE_LINE = "MAKE_LINE"
    PREP = "PREP"
    HOSPITALITY = "HOSPITALITY"


class RefillMode(str, Enum):
    STANDARD = "STANDARD"
    FORECAST = "FORECAST"


class CustomizationAction(str, Enum):
    EXTRA = "EXTRA"
    REMOVE = "REMOVE"
    SUBSTITUTE = "SUBSTITUTE"


class VerificationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# ── Entities (common_fields: true — id + created_at + updated_at + version) ──


class Restaurant(TypedDict, total=False):
    id: str
    name: str
    city: str
    created_at: str
    updated_at: str
    version: int


class AssemblyLine(TypedDict, total=False):
    id: str
    restaurant_id: str
    name: str
    line_type: str
    service_rate_seconds_per_bowl: int
    status: str
    posture: str
    last_sanitation_completed_at: Optional[str]
    next_sanitation_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ingredient(TypedDict, total=False):
    id: str
    sku: str
    name: str
    station_type: str
    shelf_life_minutes: int
    allergen_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Recipe(TypedDict, total=False):
    id: str
    restaurant_id: str
    name: str
    base_complexity: int
    portion_spec: List[Dict[str, Any]]
    is_available: bool
    created_at: str
    updated_at: str
    version: int


class Hopper(TypedDict, total=False):
    id: str
    line_id: str
    ingredient_id: str
    capacity_grams: float
    station_slot: int
    calibration_coefficient: float
    status: str
    current_grams: float
    initial_load_grams: float
    cumulative_dispensed_grams: float
    cumulative_refilled_grams: float
    cumulative_waste_grams: float
    drift_pct: Optional[float]
    drift_window_anchor: str
    created_at: str
    updated_at: str
    version: int


class RefillTask(TypedDict, total=False):
    id: str
    hopper_id: str
    ingredient_id: str
    requested_grams: float
    allocated_grams: float
    prep_batch_id: Optional[str]
    desired_ready_at: str
    auto_created: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PrepBatch(TypedDict, total=False):
    id: str
    restaurant_id: str
    ingredient_id: str
    quantity_grams: float
    allocated_grams: float
    consumed_grams: float
    available_grams: float
    status: str
    ready_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    restaurant_id: str
    recipe_id: str
    customizations: List[Dict[str, Any]]
    complexity_score: int
    route: str
    assigned_line_id: str
    status: str
    queue_entered_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    remake_count: int
    expected_total_grams: float
    estimated_queue_seconds: int
    actual_queue_seconds: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SubstitutionRule(TypedDict, total=False):
    id: str
    restaurant_id: str
    from_ingredient_id: str
    to_ingredient_id: str
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SanitationCycle(TypedDict, total=False):
    id: str
    line_id: str
    scheduled_start: str
    scheduled_end: str
    actual_started_at: Optional[str]
    actual_completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LaborAssignment(TypedDict, total=False):
    id: str
    restaurant_id: str
    staff_user_id: str
    from_role: str
    to_role: str
    window_start: str
    window_end: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


# ── Append-only records (common_fields: false — only id + created_at) ──


class PortionVerification(TypedDict, total=False):
    id: str
    created_at: str
    order_id: str
    hopper_id: str
    ingredient_id: str
    expected_grams: float
    actual_grams: float
    variance_pct: float
    result: str
    recorded_by_user_id: str


class CalibrationAdjustment(TypedDict, total=False):
    id: str
    created_at: str
    hopper_id: str
    old_coefficient: float
    new_coefficient: float
    drift_pct_observed: Optional[float]
    approved_by_user_id: str
    adjusted_at: str
