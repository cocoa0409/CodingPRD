"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    FACILITY_PLANNER = "FacilityPlanner"
    ROUTE_DISPATCHER = "RouteDispatcher"
    CAFE_MANAGER = "CafeManager"
    DONATION_COORDINATOR = "DonationCoordinator"
    FINANCE_ADMIN = "FinanceAdmin"


class DoughCategory(str, Enum):
    CONVENTIONAL = "CONVENTIONAL"
    ARTISAN = "ARTISAN"


class OwnershipType(str, Enum):
    COMPANY = "COMPANY"
    FRANCHISE = "FRANCHISE"


class AdjustmentReason(str, Enum):
    WEATHER = "WEATHER"
    EVENT = "EVENT"


class DemandAdjustmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RESCINDED = "RESCINDED"


class CafeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"
    PLANNED = "PLANNED"
    ROUTED = "ROUTED"
    DELIVERED = "DELIVERED"
    SHIPPED_SHORT = "SHIPPED_SHORT"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CREDITED = "CREDITED"


class ProductionPlanStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"


class DeliveryRouteStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RouteStopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    ON_TIME = "ON_TIME"
    LATE = "LATE"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class CafeScheduleStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class BakeEntryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PROOFING = "PROOFING"
    BAKING = "BAKING"
    COMPLETED = "COMPLETED"
    DISCARDED = "DISCARDED"


class DonationPickupStatus(str, Enum):
    LOGGED = "LOGGED"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class BillingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class DoughFacility(TypedDict, total=False):
    id: str
    name: str
    effective_capacity_units: int
    created_at: str
    updated_at: str
    version: int


class DoughType(TypedDict, total=False):
    id: str
    code: str
    category: str
    shelf_life_hours: int
    order_cutoff_local: str
    substitution_allowed: bool
    flat_transfer_price: float
    created_at: str
    updated_at: str
    version: int


class Cafe(TypedDict, total=False):
    id: str
    name: str
    facility_id: str
    ownership_type: str
    credit_limit_cents: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class DemandAdjustment(TypedDict, total=False):
    id: str
    cafe_id: str
    production_date: str
    reason: str
    demand_delta_pct: int
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CafeOrder(TypedDict, total=False):
    id: str
    cafe_id: str
    dough_type_id: str
    production_date: str
    quantity: int
    adjusted_quantity: int
    status: str
    billing_status: str
    actual_quantity: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ProductionPlan(TypedDict, total=False):
    id: str
    facility_id: str
    production_date: str
    status: str
    total_effective_units: int
    over_capacity: bool
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict, total=False):
    id: str
    facility_id: str
    production_date: str
    status: str
    vehicle_capacity_units: int
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    seq: int
    cafe_id: str
    planned_arrival: str
    window_start_local: str
    window_end_local: str
    status: str
    actual_arrival: Optional[str]
    planned_units: int
    loaded_units: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CafeSchedule(TypedDict, total=False):
    id: str
    cafe_id: str
    business_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BakeEntry(TypedDict, total=False):
    id: str
    schedule_id: str
    cafe_order_id: str
    quantity: int
    proof_start_at: str
    proof_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DonationPickup(TypedDict, total=False):
    id: str
    cafe_id: str
    schedule_id: str
    partner_name: str
    unsold_conventional: int
    unsold_artisan: int
    credit_amount: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict, total=False):
    id: str
    facility_id: str
    period_start: str
    period_end: str
    status: str
    admin_pool_cents: int
    total_cafe_hours: int
    created_at: str
    updated_at: str
    version: int


class SettlementLine(TypedDict, total=False):
    id: str
    billing_period_id: str
    cafe_id: str
    cafe_hours: int
    direct_invoice_cents: int
    allocated_indirect_cents: int
    burden_share: float
    allocated_amount_cents: int
    unit_allocated_cost: Optional[float]
    cafe_total_units: int
    created_at: str
    updated_at: str
    version: int
