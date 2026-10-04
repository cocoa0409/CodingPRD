"""Domain types: entity TypedDicts, status enums and the role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FIELD_COORDINATOR = "FieldCoordinator"
    FOOD_SAFETY_OFFICER = "FoodSafetyOfficer"
    PARTNERSHIP_LEAD = "PartnershipLead"
    PRODUCTION_PLANNER = "ProductionPlanner"
    SOURCING_OFFICER = "SourcingOfficer"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    DONOR_LIAISON = "DonorLiaison"
    KITCHEN_OPERATOR = "KitchenOperator"
    SITE_COORDINATOR = "SiteCoordinator"


class IncidentStatus(str, Enum):
    MONITORING = "MONITORING"
    ACTIVE = "ACTIVE"
    WINDING_DOWN = "WINDING_DOWN"
    CLOSED = "CLOSED"


class DisasterType(str, Enum):
    EARTHQUAKE = "EARTHQUAKE"
    FLOOD = "FLOOD"
    HURRICANE = "HURRICANE"
    WILDFIRE = "WILDFIRE"
    CONFLICT = "CONFLICT"
    EPIDEMIC = "EPIDEMIC"


class AccessConstraint(str, Enum):
    OPEN = "OPEN"
    LIMITED = "LIMITED"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class AssessmentMode(str, Enum):
    RAPID = "RAPID"
    DURABLE = "DURABLE"


class AssessmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"


class PowerSource(str, Enum):
    GRID = "GRID"
    GENERATOR = "GENERATOR"
    SOLAR = "SOLAR"
    NONE = "NONE"


class WaterSource(str, Enum):
    PIPED = "PIPED"
    TRUCKED = "TRUCKED"
    WELL = "WELL"
    NONE = "NONE"


class FieldKitchenStatus(str, Enum):
    SITED = "SITED"
    UTILITIES_PENDING = "UTILITIES_PENDING"
    FOOD_SAFETY_CLEARED = "FOOD_SAFETY_CLEARED"
    OPERATIONAL = "OPERATIONAL"
    SUSPENDED = "SUSPENDED"
    DEMOBILIZED = "DEMOBILIZED"


class ContractStatus(str, Enum):
    PROSPECT = "PROSPECT"
    VETTING = "VETTING"
    CONTRACTED = "CONTRACTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ProductionStatus(str, Enum):
    IDLE = "IDLE"
    PRODUCING = "PRODUCING"
    AT_CAPACITY = "AT_CAPACITY"
    COOLDOWN = "COOLDOWN"


class MealOrderStatus(str, Enum):
    PLACED = "PLACED"
    IN_PRODUCTION = "IN_PRODUCTION"
    QUALITY_HOLD = "QUALITY_HOLD"
    READY = "READY"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DietaryTag(str, Enum):
    HALAL = "HALAL"
    VEGETARIAN = "VEGETARIAN"
    VEGAN = "VEGAN"
    NUT_FREE = "NUT_FREE"
    GLUTEN_FREE = "GLUTEN_FREE"
    LOW_SODIUM = "LOW_SODIUM"


class SupplierStatus(str, Enum):
    PROSPECT = "PROSPECT"
    APPROVED = "APPROVED"
    PREFERRED = "PREFERRED"
    SUSPENDED = "SUSPENDED"


class PurchaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class SiteType(str, Enum):
    SHELTER = "SHELTER"
    HOSPITAL = "HOSPITAL"
    NEIGHBORHOOD = "NEIGHBORHOOD"
    SCHOOL = "SCHOOL"
    COMMUNITY_CENTER = "COMMUNITY_CENTER"


class DistributionSiteStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    SERVICE_ALERT = "SERVICE_ALERT"
    CLOSED = "CLOSED"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    LOADING = "LOADING"
    EN_ROUTE = "EN_ROUTE"
    DELIVERING = "DELIVERING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class StopStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class CommitmentStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RECEIVED = "RECEIVED"
    ALLOCATED = "ALLOCATED"
    PARTIALLY_DISBURSED = "PARTIALLY_DISBURSED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class Earmark(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    FIELD_KITCHENS = "FIELD_KITCHENS"
    RESTAURANT_ACTIVATION = "RESTAURANT_ACTIVATION"
    INGREDIENT_SOURCING = "INGREDIENT_SOURCING"
    LOGISTICS = "LOGISTICS"


class VehicleType(str, Enum):
    CAR = "CAR"
    VAN = "VAN"
    TRUCK = "TRUCK"
    MOTORCYCLE = "MOTORCYCLE"


# Every entity in this API carries the same four system-managed properties.
class Incident(TypedDict):
    id: str
    name: str
    country_code: str
    disaster_type: str
    severity_level: int
    target_daily_meals: int
    funding_ceiling_cents: int
    currency_code: str
    population_dietary_requirements: List[str]
    status: str
    activated_at: Optional[str]
    wind_down_started_at: Optional[str]
    closed_at: Optional[str]
    committed_cents: int
    spent_cents: int
    delivered_meal_total: int
    local_sourcing_pct: int
    cost_per_meal_cents: int
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    incident_id: str
    assessed_at: str
    population_affected: int
    estimated_daily_meal_need: int
    access_constraint: str
    water_available: bool
    power_available: bool
    partner_kitchens_identified: int
    assessment_mode: str
    feeding_priority_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FieldKitchen(TypedDict):
    id: str
    incident_id: str
    assessment_id: str
    site_name: str
    latitude: float
    longitude: float
    power_source: str
    water_source: str
    refrigeration_hours_available: int
    daily_capacity_meals: int
    site_status: str
    food_safety_score: int
    last_inspection_at: Optional[str]
    suspended_at: Optional[str]
    activated_at: Optional[str]
    demobilized_at: Optional[str]
    runs_today_count: int
    created_at: str
    updated_at: str
    version: int


class PartnerKitchen(TypedDict):
    id: str
    incident_id: str
    business_name: str
    owner_name: str
    cuisine_tags: List[str]
    daily_capacity_meals: int
    per_meal_price_cents: int
    bank_verified: bool
    vetting_score: int
    contract_status: str
    production_status: str
    quality_score: int
    meals_produced_total: int
    meals_produced_today: int
    production_started_at: Optional[str]
    cooldown_until: Optional[str]
    contracted_at: Optional[str]
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MealOrder(TypedDict):
    id: str
    incident_id: str
    partner_kitchen_id: str
    distribution_run_id: Optional[str]
    menu_name: str
    dietary_tags: List[str]
    ordered_meals: int
    scheduled_start: str
    production_hours: int
    status: str
    produced_meals: Optional[int]
    rejected_meals: Optional[int]
    accepted_meals: int
    rework_count: int
    quality_check_score: Optional[int]
    subtotal_cents: int
    logistics_fee_cents: int
    volume_discount_cents: int
    provisional_cost_cents: int
    final_cost_cents: Optional[int]
    placed_at: str
    ready_at: Optional[str]
    delivered_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    incident_id: str
    producer_name: str
    locality: str
    product_categories: List[str]
    payment_terms_days: int
    status: str
    cash_flow_received_cents: int
    reliability_score: int
    delivered_purchase_count: int
    disputed_purchase_count: int
    created_at: str
    updated_at: str
    version: int


class IngredientPurchase(TypedDict):
    id: str
    incident_id: str
    supplier_id: str
    partner_kitchen_id: str
    item_description: str
    quantity_kg: float
    unit_price_cents_per_kg: int
    amount_cents: int
    status: str
    requested_at: str
    delivered_at: Optional[str]
    paid_at: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionSite(TypedDict):
    id: str
    incident_id: str
    site_name: str
    site_type: str
    population_served: int
    daily_meal_request: int
    access_constraint: str
    status: str
    received_meals_total: int
    skipped_stop_count: int
    delivered_stop_count: int
    created_at: str
    updated_at: str
    version: int


class DistributionRun(TypedDict):
    id: str
    incident_id: str
    field_kitchen_id: str
    driver_name: str
    driver_phone: str
    driver_safety_training_completed: bool
    vehicle_type: str
    planned_date: str
    window_start: str
    window_end: str
    loaded_meals: int
    fuel_cost_cents: int
    handling_cost_cents: int
    status: str
    total_cost_cents: int
    unallocated_cost_cents: int
    delivered_meals: int
    returned_meals: int
    completed_at: Optional[str]
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionStop(TypedDict):
    id: str
    distribution_run_id: str
    distribution_site_id: str
    stop_sequence: int
    planned_meals: int
    delivered_meals: int
    allocated_cost_cents: int
    status: str
    failure_reason: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonorCommitment(TypedDict):
    id: str
    incident_id: str
    donor_name: str
    amount_cents: int
    earmark: str
    status: str
    received_at: Optional[str]
    allocated_cents: int
    disbursed_cents: int
    remaining_cents: int
    created_at: str
    updated_at: str
    version: int
