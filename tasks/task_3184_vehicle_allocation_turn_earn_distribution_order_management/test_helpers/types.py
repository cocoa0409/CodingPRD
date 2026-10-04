"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    REGIONAL_ALLOCATOR = "RegionalAllocator"
    DEALER = "Dealer"
    PRODUCTION_SCHEDULER = "ProductionScheduler"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    COMMODITY_MANAGER = "CommodityManager"


class RegionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class DealerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ModelLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class CommodityStatus(str, Enum):
    CONSTRAINED = "CONSTRAINED"
    RESOLVED = "RESOLVED"


class RestrictionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class RunStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class DealerAllocationStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class OrderState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SCHEDULED = "SCHEDULED"
    BUILT = "BUILT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class BuildState(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING_RETROFIT = "PENDING_RETROFIT"
    RETROFITTED = "RETROFITTED"


class OrderKind(str, Enum):
    RETAIL = "RETAIL"
    STOCK = "STOCK"


class TradeState(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    EXECUTED = "EXECUTED"


class AppealState(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class AppealType(str, Enum):
    NEW_POINT = "NEW_POINT"
    MARKET_GAP = "MARKET_GAP"


class IncentiveKind(str, Enum):
    AGED_INVENTORY_CREDIT = "AGED_INVENTORY_CREDIT"
    VOLUME_BONUS = "VOLUME_BONUS"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ShipmentState(str, Enum):
    PLANNED = "PLANNED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class Region(TypedDict):
    id: str
    code: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict):
    id: str
    region_id: str
    dealer_code: str
    name: str
    opened_on: str
    status: str
    carryover_credit_units: float
    created_at: str
    updated_at: str
    version: int


class ModelLine(TypedDict):
    id: str
    model_code: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Commodity(TypedDict):
    id: str
    code: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CommodityRestriction(TypedDict):
    id: str
    commodity_id: str
    model_line_id: str
    effective_from: str
    effective_to: Optional[str]
    install_rate_pct: int
    allow_partial_build: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationRun(TypedDict):
    id: str
    period: str
    model_line_id: str
    base_units: int
    status: str
    published_at: Optional[str]
    lookback_start: str
    lookback_end: str
    retail_priority_pct: int
    created_at: str
    updated_at: str
    version: int


class DealerAllocation(TypedDict):
    id: str
    run_id: str
    dealer_id: str
    base_units: int
    adjustment_units: int
    final_units: int
    consumed_units: int
    retail_reserved_units: int
    retail_consumed_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DealerModelLine(TypedDict):
    id: str
    dealer_id: str
    model_line_id: str
    reported_sales_units: int
    avg_inventory_units: float
    days_supply: float
    earned_credit_units: float
    created_at: str
    updated_at: str
    version: int


class VehicleOrder(TypedDict):
    id: str
    dealer_id: str
    model_line_id: str
    run_id: str
    order_kind: str
    customer_ref: Optional[str]
    configuration: dict
    state: str
    build_state: str
    retrofit_of_order_id: Optional[str]
    consumed_units: int
    scheduled_week: Optional[str]
    scheduled_at: Optional[str]
    built_at: Optional[str]
    delivered_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DealerTrade(TypedDict):
    id: str
    from_dealer_id: str
    to_dealer_id: str
    run_id: str
    units: int
    state: str
    counter_units: Optional[int]
    expires_at: str
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    dealer_id: str
    run_id: str
    appeal_type: str
    requested_units: int
    granted_units: Optional[int]
    state: str
    filed_at: str
    created_at: str
    updated_at: str
    version: int


class IncentiveProgram(TypedDict):
    id: str
    code: str
    model_line_id: str
    kind: str
    params: dict
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict):
    id: str
    code: str
    name: str
    weekly_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    carrier_id: str
    pickup_week: str
    state: str
    picked_up_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
