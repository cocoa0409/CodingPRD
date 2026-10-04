"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class SupplyCenterStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class CenterPosture(str, Enum):
    ACTIVE = "ACTIVE"
    CONSTRAINED = "CONSTRAINED"
    SURGE_MODE = "SURGE_MODE"
    SUSPENDED = "SUSPENDED"


class StoreStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ComplianceTier(str, Enum):
    FULL_COMPLIANCE = "FULL_COMPLIANCE"
    PROBATION = "PROBATION"
    NON_COMPLIANT = "NON_COMPLIANT"


class RebateEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    CONDITIONAL = "CONDITIONAL"
    INELIGIBLE = "INELIGIBLE"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"
    RECALLED = "RECALLED"


class ProductCategory(str, Enum):
    DOUGH = "DOUGH"
    FOOD_INGREDIENT = "FOOD_INGREDIENT"
    EQUIPMENT = "EQUIPMENT"
    SMALLWARES = "SMALLWARES"
    PACKAGING = "PACKAGING"


class StoreTier(str, Enum):
    STANDARD = "STANDARD"
    VOLUME_DISCOUNT = "VOLUME_DISCOUNT"
    PREMIUM = "PREMIUM"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StopStatus(str, Enum):
    PENDING = "PENDING"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    SHORTED = "SHORTED"
    CANCELLED = "CANCELLED"


class PriceBookStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class RebatePoolStatus(str, Enum):
    OPEN = "OPEN"
    CALCULATING = "CALCULATING"
    SETTLING = "SETTLING"
    CLOSED = "CLOSED"


class LedgerEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    HOLDBACK = "HOLDBACK"
    SETTLEMENT = "SETTLEMENT"
    ADJUSTMENT = "ADJUSTMENT"
    FORFEITURE = "FORFEITURE"


class LedgerStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class AgreementType(str, Enum):
    EXCLUSIVE_PURCHASE = "EXCLUSIVE_PURCHASE"
    APPROVED_SUPPLIER = "APPROVED_SUPPLIER"
    BRAND_STANDARD = "BRAND_STANDARD"


class AgreementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    BREACHED = "BREACHED"
    CURED = "CURED"
    TERMINATED = "TERMINATED"


class PromotionStatus(str, Enum):
    FORECASTED = "FORECASTED"
    CONFIRMED = "CONFIRMED"
    EXECUTING = "EXECUTING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CapacityPlanStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    RECONCILED = "RECONCILED"
    OVERBOOKED = "OVERBOOKED"


class VarianceSeverity(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class VarianceStatus(str, Enum):
    PENDING = "PENDING"
    FINALIZED = "FINALIZED"
    FLAGGED = "FLAGGED"


class DayOfWeek(str, Enum):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


class UserRole(str, Enum):
    SUPPLY_CHAIN_ADMIN = "SupplyChainAdmin"
    STORE_MANAGER = "StoreManager"
    ROUTE_COORDINATOR = "RouteCoordinator"
    ANY = "Any"


class SupplyCenter(TypedDict, total=False):
    id: str
    center_code: str
    display_name: str
    base_weekly_capacity_units: int
    surge_capacity_multiplier: float
    ops_run_index: int
    rebate_pool_balance_cents: int
    rebate_pool_locked_cents: int
    posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    center_id: str
    store_number: str
    operator_name: str
    compliance_tier: str
    exclusive_purchase_pct: float
    rebate_eligibility_status: str
    outstanding_balance_cents: int
    credit_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    center_id: str
    sku: str
    name: str
    category: str
    base_cost_cents_per_unit: int
    shelf_life_days: Optional[int]
    is_promotion_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict, total=False):
    id: str
    center_id: str
    route_code: str
    day_of_week: str
    truck_capacity_units: int
    assigned_store_ids: List[str]
    status: str
    dispatched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryStop(TypedDict, total=False):
    id: str
    route_id: str
    store_id: str
    sequence_number: int
    estimated_arrival: str
    actual_arrival: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    store_id: str
    center_id: str
    week_start_date: str
    status: str
    subtotal_cents: int
    markup_cents: int
    delivery_fee_cents: int
    total_cents: int
    theoretical_usage_cents: int
    actual_usage_cents: int
    food_cost_variance_pct: Optional[float]
    promotion_id: Optional[str]
    route_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    quantity: int
    unit_price_cents: int
    extended_price_cents: int
    theoretical_usage_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceBook(TypedDict, total=False):
    id: str
    center_id: str
    product_id: str
    store_tier: str
    markup_pct: float
    min_quantity: int
    effective_from: str
    effective_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RebatePool(TypedDict, total=False):
    id: str
    center_id: str
    quarter: str
    pool_total_cents: int
    distributed_cents: int
    holdback_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RebateLedger(TypedDict, total=False):
    id: str
    pool_id: str
    store_id: str
    entry_type: str
    amount_cents: int
    running_balance_cents: int
    source_order_id: Optional[str]
    settlement_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceAgreement(TypedDict, total=False):
    id: str
    store_id: str
    agreement_type: str
    start_date: str
    end_date: Optional[str]
    exclusive_purchase_threshold: float
    status: str
    breach_count: int
    cure_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PromotionEvent(TypedDict, total=False):
    id: str
    center_id: str
    promotion_code: str
    start_date: str
    end_date: str
    surge_multiplier: float
    affected_product_ids: List[str]
    capacity_reserved_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityPlan(TypedDict, total=False):
    id: str
    center_id: str
    week_start_date: str
    baseline_units: int
    surge_units: int
    allocated_units: int
    available_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FoodCostVariance(TypedDict, total=False):
    id: str
    store_id: str
    week_start_date: str
    theoretical_cents: int
    actual_cents: int
    variance_cents: int
    variance_pct: Optional[float]
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int
