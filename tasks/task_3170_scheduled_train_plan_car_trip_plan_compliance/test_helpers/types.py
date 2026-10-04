"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity catalog and state machines.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class TrainPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class YardPosture(str, Enum):
    OPEN = "OPEN"
    CONGESTED = "CONGESTED"
    EMBARGOED = "EMBARGOED"


class CrewPoolStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class CrewCraft(str, Enum):
    CONDUCTOR = "CONDUCTOR"
    ENGINEER = "ENGINEER"


class LocomotiveStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    BAD_ORDER = "BAD_ORDER"


class ShipmentStatus(str, Enum):
    OPEN = "OPEN"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TripPlanStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    MISSED_CONNECTION = "MISSED_CONNECTION"
    REPLANNED = "REPLANNED"


class ComplianceStatus(str, Enum):
    ON_PLAN = "ON_PLAN"
    AT_RISK = "AT_RISK"
    OFF_PLAN = "OFF_PLAN"


class TripLegStatus(str, Enum):
    PLANNED = "PLANNED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    REPLACED = "REPLACED"


class ConnectionStatus(str, Enum):
    PENDING = "PENDING"
    MADE = "MADE"
    MISSED = "MISSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class TrainDepartureStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class CarEventType(str, Enum):
    TRAIN_DEPARTURE = "TRAIN_DEPARTURE"
    YARD_ARRIVAL = "YARD_ARRIVAL"
    CLASSIFICATION_COMPLETE = "CLASSIFICATION_COMPLETE"
    PLACED_DELIVERED = "PLACED_DELIVERED"


class ExceptionType(str, Enum):
    MISSED_CONNECTION = "MISSED_CONNECTION"
    DWELL_OVERAGE = "DWELL_OVERAGE"
    DEPARTURE_DELAY = "DEPARTURE_DELAY"
    PICKUP_MISS = "PICKUP_MISS"
    DELIVERY_MISS = "DELIVERY_MISS"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"


class RootCauseCode(str, Enum):
    CREW_SHORTAGE = "CREW_SHORTAGE"
    POWER_SHORTAGE = "POWER_SHORTAGE"
    YARD_CONGESTION = "YARD_CONGESTION"
    CUSTOMER_DELAY = "CUSTOMER_DELAY"
    OTHER = "OTHER"


class UserRole(str, Enum):
    NETWORK_PLANNER = "NetworkPlanner"
    CREW_DISPATCHER = "CrewDispatcher"
    POWER_PLANNER = "PowerPlanner"
    TERMINAL_SUPERINTENDENT = "TerminalSuperintendent"
    SERVICE_MANAGER = "ServiceManager"
    ANY = "Any"


class TrainPlan(TypedDict, total=False):
    id: str
    train_symbol: str
    origin_yard_id: str
    destination_yard_id: str
    scheduled_departure_utc: str
    cutoff_minutes: int
    frequency_mask: List[str]
    route_distance_miles: float
    dwell_benchmark_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Yard(TypedDict, total=False):
    id: str
    yard_code: str
    dwell_benchmark_hours: float
    classification_capacity_cars: int
    posture: str
    current_dwell_overage_hours: float
    created_at: str
    updated_at: str
    version: int


class CrewPool(TypedDict, total=False):
    id: str
    home_yard_id: str
    craft: str
    service_date: str
    crews_available: int
    crews_booked: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Locomotive(TypedDict, total=False):
    id: str
    unit_number: str
    current_yard_id: str
    horsepower: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    customer_code: str
    name: str
    service_credit_balance: int
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    customer_id: str
    origin_yard_id: str
    destination_yard_id: str
    car_count: int
    first_mile_pickup_by: str
    last_mile_delivery_by: str
    committed_route_miles: float
    trip_plan_status: str
    compliance_status: str
    car_velocity_mph: Optional[float]
    total_missed_connections: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TripLeg(TypedDict, total=False):
    id: str
    shipment_id: str
    train_plan_id: str
    leg_sequence: int
    planned_connection_time: Optional[str]
    planned_departure_utc: str
    actual_departure_utc: Optional[str]
    connection_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainDeparture(TypedDict, total=False):
    id: str
    train_plan_id: str
    service_date: str
    crew_pool_id: str
    locomotive_id: str
    car_count_planned: int
    crew_hours_estimated: float
    actual_departure_utc: Optional[str]
    departure_variance_minutes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarEvent(TypedDict, total=False):
    id: str
    shipment_id: str
    yard_id: str
    event_type: str
    occurred_at: str
    car_count: int
    created_at: str
    # Append-only log: NO updated_at, NO version (PRD: car events carry only
    # id and created_at beyond their declared fields).


class ServiceException(TypedDict, total=False):
    id: str
    shipment_id: str
    exception_type: str
    triage_notes: Optional[str]
    root_cause_code: Optional[str]
    detected_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
