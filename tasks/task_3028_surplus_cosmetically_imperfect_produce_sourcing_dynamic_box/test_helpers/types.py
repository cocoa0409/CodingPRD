"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD's §2.5 ownership rule: ten of the eleven resources
carry `updated_at` and `version`; `ColdChainPack` is created once and never
modified, so it carries only `id` and `created_at`.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class Region(str, Enum):
    NE = "NE"
    MW = "MW"
    SO = "SO"
    WE = "WE"


class InsulationProfile(str, Enum):
    LIGHT = "LIGHT"
    MEDIUM = "MEDIUM"
    HEAVY = "HEAVY"


class ForwardPosture(str, Enum):
    OPEN = "OPEN"
    CONSTRAINED = "CONSTRAINED"
    DEGRADED = "DEGRADED"


class SupplierStanding(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SupplierRelationship(str, Enum):
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"
    ON_WATCH = "ON_WATCH"
    SUSPENDED = "SUSPENDED"


class LotCategory(str, Enum):
    FRUIT = "FRUIT"
    VEGETABLE = "VEGETABLE"
    DAIRY = "DAIRY"
    BAKERY = "BAKERY"
    PANTRY = "PANTRY"
    BEVERAGE = "BEVERAGE"


class ProcurementGrade(str, Enum):
    OFF_SPEC = "OFF_SPEC"
    SURPLUS = "SURPLUS"
    SHORT_DATED = "SHORT_DATED"
    COSMETIC = "COSMETIC"


class LotStatus(str, Enum):
    QUOTED = "QUOTED"
    AWARDED = "AWARDED"
    READY = "READY"
    COMMITTED = "COMMITTED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class LotQualityStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    PASS = "PASS"
    INVESTIGATION = "INVESTIGATION"
    REJECTED = "REJECTED"


class BidStatus(str, Enum):
    PENDING = "PENDING"
    SHORTLISTED = "SHORTLISTED"
    SELECTED = "SELECTED"
    NOT_SELECTED = "NOT_SELECTED"
    WITHDRAWN = "WITHDRAWN"


class SubstantiationStatus(str, Enum):
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    SUBSTANTIATED = "SUBSTANTIATED"


class BoxOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    AWAITING_WINDOW = "AWAITING_WINDOW"
    READY_TO_BUILD = "READY_TO_BUILD"
    BUILDING = "BUILDING"
    REROUTED = "REROUTED"
    CRASHED = "CRASHED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"


class PricingStatus(str, Enum):
    UNPRICED = "UNPRICED"
    PRICED = "PRICED"
    REVISED = "REVISED"


class CuisinePreference(str, Enum):
    STANDARD = "STANDARD"
    FRUIT_FORWARD = "FRUIT_FORWARD"
    VEGGIE_FORWARD = "VEGGIE_FORWARD"
    BAKERY_FORWARD = "BAKERY_FORWARD"
    PANTRY_FORWARD = "PANTRY_FORWARD"


class BuildItemType(str, Enum):
    PREFERENCE = "PREFERENCE"
    FILLER = "FILLER"
    RETAINED = "RETAINED"


class BuildItemStatus(str, Enum):
    INCLUDED = "INCLUDED"
    REMOVED = "REMOVED"


class ColdChainSelectionStatus(str, Enum):
    SELECTED = "SELECTED"
    NOT_REQUIRED = "NOT_REQUIRED"


class ClaimStatus(str, Enum):
    IN_REVIEW = "IN_REVIEW"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class ClaimReason(str, Enum):
    SPOILED = "SPOILED"
    DAMAGED = "DAMAGED"
    MISSING_ITEM = "MISSING_ITEM"
    TEMPERATURE_ABUSE = "TEMPERATURE_ABUSE"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SKIPPED = "SKIPPED"
    AUTO_SKIPPED = "AUTO_SKIPPED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class SubscriptionCadence(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class CancellationReason(str, Enum):
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    NONPAYMENT = "NONPAYMENT"


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SUPPLIER = "Supplier"
    FULFILLMENT_OPERATOR = "FulfillmentOperator"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


# common_fields: true — id + created_at + updated_at + version
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    service_region: str
    home_fulfillment_center_id: str
    dietary_allergy_codes: List[str]
    grandfathered_service_fee: bool
    created_at: str
    updated_at: str
    version: int


class FulfillmentCenter(TypedDict):
    id: str
    code: str
    name: str
    region: str
    is_active: bool
    insulation_profile: str
    serving_cycle_index: int
    max_concurrent_building_cycles: int
    forward_posture: str
    open_claim_count: int
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    name: str
    region: str
    relationship_status: str
    reliability_score_bp: int
    lots_awarded_total: int
    lots_accepted_total: int
    lots_on_time_total: int
    claims_upheld_total: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyLot(TypedDict):
    id: str
    supplier_id: str
    fulfillment_center_id: str
    product_name: str
    category: str
    procurement_grade: str
    unit_weight_grams: int
    quantity_available: int
    unit_cost_cents: int
    harvest_date: str
    shelf_life_days: int
    expiry_date: str
    allergen_codes: List[str]
    preference_tags: List[str]
    preference_eligible: bool
    billing_weight_grams: int
    display_price_cents: int
    ready_date: str
    status: str
    quality_status: str
    arrived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SourcingBid(TypedDict):
    id: str
    supply_lot_id: str
    supplier_id: str
    bid_unit_cost_cents: int
    quantity_offered: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConventionalQuote(TypedDict):
    id: str
    supply_lot_id: str
    retailer_label: str
    source_url: str
    captured_at: str
    conventional_unit_price_cents: int
    barcode_gtin: str
    grade_equivalent: bool
    source_count: int
    is_primary: bool
    substantiation_status: str
    created_at: str
    updated_at: str
    version: int


class BoxOrder(TypedDict):
    id: str
    customer_id: str
    subscription_id: str
    serving_cycle_index: int
    fulfillment_center_id: str
    routing_region: str
    cuisine_preference: str
    status: str
    pricing_status: str
    lines_total_cents: int
    weight_total_grams: int
    conventional_total_cents: int
    order_discount_cents: int
    service_fee_cents: int
    subtotal_cents: int
    tax_cents: int
    shipped_total_cents: int
    ready_deadline: str
    build_deadline: str
    cutoff_met: bool
    build_blocked: bool
    cold_chain_selected: bool
    credit_cents_issued: int
    allocation_used_cents: int
    created_at: str
    updated_at: str
    version: int


class BoxBuildItem(TypedDict):
    id: str
    box_order_id: str
    supply_lot_id: str
    category: str
    units: int
    billed_unit_weight_grams: int
    line_price_cents: int
    item_type: str
    status: str
    allocation_credited_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — created once, never modified: ONLY id + created_at
class ColdChainPack(TypedDict):
    id: str
    box_order_id: str
    lane_fulfillment_center_id: str
    cold_item_weight_grams: int
    insulation_grade: str
    coolant_units: int
    lane_transit_days: int
    selection_status: str
    created_at: str


class QualityClaim(TypedDict):
    id: str
    box_order_id: str
    box_build_item_id: str
    supply_lot_id: str
    reason_code: str
    photo_url: str
    requested_credit_cents: int
    credited_cents: int
    status: str
    outcome: Optional[str]
    cited_lot_quality_status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    cadence: str
    home_fulfillment_center_id: str
    serving_cycle_index: int
    skipped_cycle_index: Optional[int]
    skipped_on: Optional[str]
    paused_at: Optional[str]
    resumed_at: Optional[str]
    pause_count: int
    status: str
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int