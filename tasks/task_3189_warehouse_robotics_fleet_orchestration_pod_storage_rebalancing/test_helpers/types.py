"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the full common-field set (id, created_at, updated_at,
version) per the PRD's common resource properties section.
"""
from enum import Enum
from typing import TypedDict, Optional


class ZonePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class DriveUnitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EN_ROUTE = "EN_ROUTE"
    AT_STATION = "AT_STATION"
    PARKED = "PARKED"
    CHARGING = "CHARGING"
    MAINTENANCE = "MAINTENANCE"
    STRANDED = "STRANDED"
    RETIRED = "RETIRED"


class PodStatus(str, Enum):
    IN_STORAGE = "IN_STORAGE"
    RESERVED = "RESERVED"
    AT_STATION = "AT_STATION"
    QUARANTINED = "QUARANTINED"


class VelocityClass(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PickStationStatus(str, Enum):
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class CustomerOrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    CUTOFF_MISSED = "CUTOFF_MISSED"


class PickTaskStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    PICKING = "PICKING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StowTaskStatus(str, Enum):
    PENDING = "PENDING"
    PLACED = "PLACED"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"


class ChargingSessionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ABORTED = "ABORTED"


class MaintenanceWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class MaintenanceWindowKind(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    CORRECTIVE = "CORRECTIVE"


class FloorExceptionKind(str, Enum):
    DROPPED_ITEM = "DROPPED_ITEM"
    BLOCKED_PATH = "BLOCKED_PATH"
    STRANDED_ROBOT = "STRANDED_ROBOT"


class FloorExceptionStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED_ROBOT = "TRIAGED_ROBOT"
    TRIAGED_HUMAN = "TRIAGED_HUMAN"
    RESOLVED = "RESOLVED"


class HumanEntryPermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class SoftwareReleaseStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"
    FLOOR_LIVE = "FLOOR_LIVE"
    ROLLED_BACK = "ROLLED_BACK"


class UserRole(str, Enum):
    FLEET_ADMIN = "FleetAdmin"
    FLOW_CONTROLLER = "FlowController"
    STATION_OPERATOR = "StationOperator"
    FLOOR_SUPERVISOR = "FloorSupervisor"
    SAFETY_OFFICER = "SafetyOfficer"
    MAINTENANCE_TECH = "MaintenanceTech"
    RELEASE_ENGINEER = "ReleaseEngineer"


class FloorZone(TypedDict, total=False):
    id: str
    zone_code: str
    grid_x: int
    grid_y: int
    width: int
    height: int
    posture: str
    max_human_occupancy: int
    created_at: str
    updated_at: str
    version: int


class DriveUnit(TypedDict, total=False):
    id: str
    unit_code: str
    status: str
    home_zone_id: str
    battery_pct: int
    firmware_release_id: Optional[str]
    odometer_cells: int
    charge_cycle_count: int
    created_at: str
    updated_at: str
    version: int


class Charger(TypedDict, total=False):
    id: str
    zone_id: str
    slot_count: int
    slots_in_use: int
    created_at: str
    updated_at: str
    version: int


class Pod(TypedDict, total=False):
    id: str
    pod_code: str
    zone_id: str
    slot_capacity: int
    slots_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Sku(TypedDict, total=False):
    id: str
    sku_code: str
    velocity_class: str
    total_units_on_hand: int
    total_units_reserved: int
    created_at: str
    updated_at: str
    version: int


class InventorySlot(TypedDict, total=False):
    id: str
    pod_id: str
    sku_id: str
    quantity: int
    quantity_reserved: int
    accessibility_rank: int
    created_at: str
    updated_at: str
    version: int


class PickStation(TypedDict, total=False):
    id: str
    station_code: str
    zone_id: str
    max_queue: int
    queue_length: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerOrder(TypedDict, total=False):
    id: str
    order_code: str
    status: str
    cutoff_at: str
    priority: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    sku_id: str
    quantity: int
    quantity_picked: int
    created_at: str
    updated_at: str
    version: int


class PickTask(TypedDict, total=False):
    id: str
    order_id: str
    line_id: str
    pod_id: str
    station_id: str
    drive_unit_id: Optional[str]
    quantity: int
    status: str
    sequence_index: Optional[int]
    est_cost: Optional[float]
    actual_cost: Optional[float]
    created_at: str
    updated_at: str
    version: int


class StowTask(TypedDict, total=False):
    id: str
    sku_id: str
    quantity: int
    pod_id: Optional[str]
    status: str
    placement_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ChargingSession(TypedDict, total=False):
    id: str
    charger_id: str
    drive_unit_id: str
    started_at: str
    ended_at: Optional[str]
    status: str
    charge_credit_pct: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict, total=False):
    id: str
    drive_unit_id: str
    starts_at: str
    ends_at: str
    status: str
    kind: str
    created_at: str
    updated_at: str
    version: int


class FloorException(TypedDict, total=False):
    id: str
    kind: str
    zone_id: str
    pod_id: Optional[str]
    drive_unit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HumanEntryPermit(TypedDict, total=False):
    id: str
    zone_id: str
    exception_id: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShiftPlan(TypedDict, total=False):
    id: str
    plan_date: str
    staffed_pickers: int
    planned_units: int
    projected_units: int
    feasible: bool
    created_at: str
    updated_at: str
    version: int


class SoftwareRelease(TypedDict, total=False):
    id: str
    release_code: str
    status: str
    safety_check_passed: bool
    defect_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int
