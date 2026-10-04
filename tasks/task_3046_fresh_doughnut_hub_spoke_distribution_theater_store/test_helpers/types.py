"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    HUB_MANAGER = "HubManager"
    ROUTE_PLANNER = "RoutePlanner"
    ROUTE_DRIVER = "RouteDriver"
    DOOR_MANAGER = "DoorManager"


class NetworkPosture(str, Enum):
    OPEN = "OPEN"
    DEGRADED = "DEGRADED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class DoorKind(str, Enum):
    THEATER = "THEATER"
    SPOKE = "SPOKE"
    GROCERY = "GROCERY"
    PARTNER = "PARTNER"


class Ownership(str, Enum):
    COMPANY = "COMPANY"
    FRANCHISE = "FRANCHISE"


class DoorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class LineKind(str, Enum):
    CONTINUOUS_FRYER = "CONTINUOUS_FRYER"
    GLAZE_WATERFALL = "GLAZE_WATERFALL"


class LineStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    MAINTENANCE = "MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class CollectionKind(str, Enum):
    CORE = "CORE"
    SEASONAL = "SEASONAL"
    LICENSED = "LICENSED"


class VarietyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class MixPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    LOCKED = "LOCKED"


class BatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMMITTED = "COMMITTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    SHORTFALL = "SHORTFALL"
    CANCELLED = "CANCELLED"


class RouteStatus(str, Enum):
    PLANNING = "PLANNING"
    LOCKED = "LOCKED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    RECONCILED = "RECONCILED"


class StopStatus(str, Enum):
    PENDING = "PENDING"
    ARRIVED = "ARRIVED"
    DELIVERED = "DELIVERED"
    MISSED = "MISSED"
    CREDITED = "CREDITED"


class DeliveryStatus(str, Enum):
    STAGED = "STAGED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class CreditStatus(str, Enum):
    NONE = "NONE"
    PENDING_PULL = "PENDING_PULL"
    CREDITED = "CREDITED"
    DISPUTED = "DISPUTED"


class CreditState(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class FundraiserStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    READY = "READY"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class HotLightWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIT = "LIT"
    EXTENDED = "EXTENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# All resource kinds carry the full common set: id, created_at, updated_at, version.

class Network(TypedDict, total=False):
    id: str
    network_code: str
    display_name: str
    network_posture: str
    ops_run_index: int
    stale_credit_pool_cents: int
    created_at: str
    updated_at: str
    version: int


class Hub(TypedDict, total=False):
    id: str
    network_id: str
    hub_code: str
    daily_capacity_dozens: int
    committed_dozens_today: int
    territory_region: str
    created_at: str
    updated_at: str
    version: int


class Door(TypedDict, total=False):
    id: str
    network_id: str
    hub_id: Optional[str]
    door_kind: str
    ownership: str
    territory_region: str
    door_status: str
    credit_balance_cents: int
    open_dispute_count: int
    created_at: str
    updated_at: str
    version: int


class EquipmentLine(TypedDict, total=False):
    id: str
    hub_id: str
    line_kind: str
    line_status: str
    rated_dozens_per_hour: int
    effective_dozens_per_hour: int
    hours_since_service: float
    service_interval_hours: int
    created_at: str
    updated_at: str
    version: int


class Variety(TypedDict, total=False):
    id: str
    network_id: str
    variety_code: str
    collection_kind: str
    active_from: str
    active_until: str
    unit_cost_cents: int
    variety_status: str
    created_at: str
    updated_at: str
    version: int


class MixPlan(TypedDict, total=False):
    id: str
    door_id: str
    effective_date: str
    mix_plan_status: str
    total_planned_dozens: int
    license_quota_dozens: int
    created_at: str
    updated_at: str
    version: int


class MixPlanLine(TypedDict, total=False):
    id: str
    mix_plan_id: str
    variety_id: str
    planned_dozens: int
    allocated_dozens: int
    created_at: str
    updated_at: str
    version: int


class ProductionBatch(TypedDict, total=False):
    id: str
    hub_id: str
    equipment_line_id: str
    production_date: str
    planned_dozens: int
    produced_dozens: Optional[int]
    batch_status: str
    fresh_until: Optional[str]
    yield_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    hub_id: str
    route_code: str
    service_date: str
    route_status: str
    vehicle_capacity_dozens: int
    loaded_dozens: int
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    door_id: str
    sequence_no: int
    window_start: str
    window_end: str
    stop_status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    route_stop_id: str
    production_batch_id: str
    dozens_shipped: int
    dozens_delivered: Optional[int]
    delivery_status: str
    credit_status: str
    freshness_override: bool
    created_at: str
    updated_at: str
    version: int


class StaleCredit(TypedDict, total=False):
    id: str
    door_id: str
    shipment_id: str
    pulled_dozens: int
    provisional_credit_cents: int
    final_credit_cents: Optional[int]
    credit_state: str
    created_at: str
    updated_at: str
    version: int


class FundraiserOrder(TypedDict, total=False):
    id: str
    door_id: str
    organization_name: str
    requested_dozens: int
    pickup_at: str
    fundraiser_status: str
    quoted_total_cents: Optional[int]
    pickup_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HotLightWindow(TypedDict, total=False):
    id: str
    door_id: str
    lit_start: str
    lit_end: str
    window_status: str
    demand_response_extend_minutes: int
    created_at: str
    updated_at: str
    version: int
