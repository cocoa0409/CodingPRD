"""Typed enumerations and resource shapes for the food waste diversion API."""

from enum import Enum
from typing import List, Optional, TypedDict


class Role(str, Enum):
    KITCHEN_STAFF = "KitchenStaff"
    SHIFT_LEAD = "ShiftLead"
    SITE_SUSTAINABILITY_MANAGER = "SiteSustainabilityManager"
    HAULER_OPERATOR = "HaulerOperator"
    CORPORATE_SUSTAINABILITY_LEAD = "CorporateSustainabilityLead"
    PLATFORM_ADMIN = "PlatformAdmin"


class CoachingPosture(str, Enum):
    MONITORING = "MONITORING"
    INTERVENTION = "INTERVENTION"
    ESCALATED = "ESCALATED"


class FoodCategory(str, Enum):
    PRODUCE = "PRODUCE"
    PROTEIN = "PROTEIN"
    PREPARED = "PREPARED"
    BAKERY = "BAKERY"
    DAIRY = "DAIRY"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class StationKind(str, Enum):
    PREP = "PREP"
    HOT_LINE = "HOT_LINE"
    DISH_RETURN = "DISH_RETURN"


class StationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class ShiftCode(str, Enum):
    AM = "AM"
    PM = "PM"
    NIGHT = "NIGHT"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LossReason(str, Enum):
    OVERPRODUCTION = "OVERPRODUCTION"
    SPOILAGE = "SPOILAGE"
    TRIM = "TRIM"
    EXPIRATION = "EXPIRATION"
    PLATE_WASTE = "PLATE_WASTE"
    CONTAMINATION = "CONTAMINATION"


class EntryStream(str, Enum):
    PRE_CONSUMER = "PRE_CONSUMER"
    POST_CONSUMER = "POST_CONSUMER"


class EntryStatus(str, Enum):
    RECORDED = "RECORDED"
    FLAGGED = "FLAGGED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class BaselineStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"


class TargetBasis(str, Enum):
    ABSOLUTE = "ABSOLUTE"
    INTENSITY = "INTENSITY"


class TargetStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    ACHIEVED = "ACHIEVED"
    MISSED = "MISSED"
    SUPERSEDED = "SUPERSEDED"


class AttainmentState(str, Enum):
    BEHIND = "BEHIND"
    ACHIEVED_PENDING = "ACHIEVED_PENDING"


class HaulerStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"


class Channel(str, Enum):
    DONATION = "DONATION"
    ANIMAL_FEED = "ANIMAL_FEED"
    COMPOST = "COMPOST"
    LANDFILL = "LANDFILL"


class LogisticsStatus(str, Enum):
    DRAFT = "DRAFT"
    STAGED = "STAGED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    TICKET_SUBMITTED = "TICKET_SUBMITTED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class TicketStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"


class AlertType(str, Enum):
    INTENSITY_BREACH = "INTENSITY_BREACH"
    OVERPRODUCTION_SPIKE = "OVERPRODUCTION_SPIKE"


class AlertSeverity(str, Enum):
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    AUTO_RESOLVED = "AUTO_RESOLVED"
    EXPIRED = "EXPIRED"


class FindingType(str, Enum):
    MISSED_CAPTURE = "MISSED_CAPTURE"
    DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
    WEIGHT_OUTLIER = "WEIGHT_OUTLIER"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class RollupStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class GoalAttainmentState(str, Enum):
    ALL_ON_TRACK = "ALL_ON_TRACK"
    NONE_ON_TRACK = "NONE_ON_TRACK"
    PARTIAL = "PARTIAL"


class Site(TypedDict):
    id: str
    name: str
    site_code: str
    region_code: str
    target_intensity_kg_per_1k_meals: float
    total_captured_weight_grams: int
    valued_waste_cost_cents: int
    diverted_weight_grams_settled: int
    diversion_rate_pct: Optional[float]
    open_alert_count: int
    coaching_posture: str
    created_at: str
    updated_at: str
    version: int


class TrackingStation(TypedDict):
    id: str
    site_id: str
    station_code: str
    station_kind: str
    calibration_due_at: str
    tare_grams: int
    capture_lock_seconds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FoodType(TypedDict):
    id: str
    name: str
    category: str
    default_cost_per_kg_cents: int
    donation_eligible: bool
    animal_feed_eligible: bool
    compostable: bool
    donation_shelf_life_hours: int
    created_at: str
    updated_at: str
    version: int


class RecipeIngredient(TypedDict):
    ingredient_name: str
    quantity_kg: float
    unit_cost_cents_per_kg: int
    trim_loss_pct: float


class Recipe(TypedDict):
    id: str
    recipe_code: str
    name: str
    ingredients: List[RecipeIngredient]
    total_ingredient_cost_cents: int
    usable_yield_kg: float
    cost_per_kg_cents: int
    published_cost_per_kg_cents: Optional[int]
    published_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    site_id: str
    shift_date: str
    shift_code: str
    meals_served: int
    status: str
    shift_waste_grams: int
    waste_intensity_kg_per_1k_meals: Optional[float]
    pre_consumer_share_pct: Optional[float]
    capture_compliance_pct: Optional[float]
    leaderboard_score: Optional[float]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WasteEntry(TypedDict):
    id: str
    site_id: str
    station_id: str
    shift_id: str
    food_type_id: str
    recipe_id: Optional[str]
    weight_grams: int
    loss_reason: str
    stream: str
    captured_at: str
    capture_window_end: str
    captured_by_user_id: str
    status: str
    catalog_cost_basis_cents: int
    recipe_cost_basis_cents: Optional[int]
    provisional_cost_cents: int
    final_cost_cents: Optional[int]
    valuation_delta_cents: Optional[int]
    effective_cost_cents: int
    routed_weight_grams: int
    unrouted_weight_grams: int
    corrects_entry_id: Optional[str]
    flag_reason: Optional[str]
    void_reason: Optional[str]
    correction_note: Optional[str]
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BaselinePeriod(TypedDict):
    id: str
    site_id: str
    start_date: str
    end_date: str
    status: str
    baseline_entry_count: int
    baseline_waste_grams: int
    baseline_waste_kg: Optional[float]
    baseline_cost_cents: int
    baseline_meals_served: int
    baseline_intensity_kg_per_1k_meals: Optional[float]
    rejection_count: int
    rejection_note: Optional[str]
    submitted_at: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReductionTarget(TypedDict):
    id: str
    site_id: str
    baseline_period_id: str
    basis: str
    target_reduction_pct: float
    min_diversion_rate_pct: float
    window_start: str
    window_end: str
    status: str
    performance_waste_grams: int
    performance_meals_served: int
    performance_intensity_kg_per_1k_meals: Optional[float]
    absolute_reduction_pct: Optional[float]
    intensity_reduction_pct: Optional[float]
    effective_reduction_pct: Optional[float]
    attainment_state: str
    activated_at: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TargetAttainment(TypedDict):
    target_id: str
    basis: str
    baseline_waste_grams: int
    baseline_intensity_kg_per_1k_meals: Optional[float]
    performance_waste_grams: int
    performance_meals_served: int
    performance_intensity_kg_per_1k_meals: Optional[float]
    absolute_reduction_pct: Optional[float]
    intensity_reduction_pct: Optional[float]
    effective_reduction_pct: Optional[float]
    target_reduction_pct: float
    min_diversion_rate_pct: float
    site_diversion_rate_pct: Optional[float]
    attainment_state: str


class Hauler(TypedDict):
    id: str
    name: str
    channels: List[str]
    rate_cents_per_tonne: int
    stop_fee_cents: int
    capacity_kg_per_pickup: float
    max_concurrent_pickups: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DiversionConsignment(TypedDict):
    id: str
    site_id: str
    hauler_id: str
    channel: str
    pickup_window_start: str
    pickup_window_end: str
    container_tare_grams: int
    logistics_status: str
    settlement_status: str
    staged_weight_grams: int
    line_count: int
    cancel_reason: Optional[str]
    staged_at: Optional[str]
    dispatched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsignmentLine(TypedDict):
    """An allocation line is an immutable event record: only ``id`` and ``created_at``."""

    id: str
    consignment_id: str
    waste_entry_id: str
    allocated_weight_grams: int
    created_by_user_id: str
    created_at: str


class HaulerTicket(TypedDict):
    id: str
    consignment_id: str
    hauler_id: str
    ticket_number: str
    gross_weight_grams: int
    ticket_date: str
    net_weight_grams: int
    billable_tonnes: float
    base_haul_fee_cents: int
    fuel_surcharge_pct: float
    fuel_surcharge_cents: int
    settlement_subtotal_cents: int
    variance_pct: Optional[float]
    variance_credit_cents: int
    settlement_total_cents: int
    status: str
    dispute_note: Optional[str]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoachingAlert(TypedDict):
    id: str
    site_id: str
    shift_id: str
    waste_entry_id: Optional[str]
    alert_type: str
    severity: str
    observed_intensity: Optional[float]
    message: str
    status: str
    acknowledged_by_user_id: Optional[str]
    resolved_by_user_id: Optional[str]
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DataQualityFinding(TypedDict):
    id: str
    site_id: str
    station_id: Optional[str]
    shift_id: Optional[str]
    waste_entry_id: Optional[str]
    finding_type: str
    detail: str
    detected_at: str
    status: str
    resolved_by_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PublishedMetrics(TypedDict):
    total_captured_weight_grams: int
    total_valued_cost_cents: int
    total_diverted_weight_grams: int
    diversion_rate_pct: Optional[float]
    sites_on_track_count: int
    goal_attainment_state: str


class CorporateRollup(TypedDict):
    id: str
    period_start: str
    period_end: str
    site_ids: List[str]
    status: str
    in_scope_site_count: int
    total_captured_weight_grams: int
    total_valued_cost_cents: int
    total_diverted_weight_grams: int
    diversion_rate_pct: Optional[float]
    sites_on_track_count: int
    goal_attainment_state: str
    prepared_by_user_id: str
    published_by_user_id: Optional[str]
    published_at: Optional[str]
    published_metrics: Optional[PublishedMetrics]
    created_at: str
    updated_at: str
    version: int


class ClockResult(TypedDict):
    current_utc: str
    reevaluated_target_ids: List[str]
    resolved_target_ids: List[str]
