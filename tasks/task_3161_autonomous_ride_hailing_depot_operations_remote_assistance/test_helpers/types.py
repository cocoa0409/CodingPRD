"""Domain types: entity TypedDicts, status enums and the role enum.

Every resource in this interface is created with the standard property set
(``id``, ``created_at``, ``updated_at``) and a system-managed ``version``
that starts at 1 and increments by one on every mutation — whether the
mutation was requested by a client or produced by the server's own
recomputation.  There are no append-only or version-less resource types in
this model, so every TypedDict below carries ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict

from . import constants as c


class UserRole(str, Enum):
    FLEET_OPERATIONS = c.ROLE_FLEET_OPERATIONS
    DEPOT_TECHNICIAN = c.ROLE_DEPOT_TECHNICIAN
    REMOTE_ASSISTANCE_OPERATOR = c.ROLE_REMOTE_ASSISTANCE_OPERATOR
    TERRITORY_PLANNER = c.ROLE_TERRITORY_PLANNER
    SAFETY_REVIEWER = c.ROLE_SAFETY_REVIEWER
    MAPPING_ENGINEER = c.ROLE_MAPPING_ENGINEER


class TerritoryPosture(str, Enum):
    PENDING = c.POSTURE_PENDING
    MAPPING = c.POSTURE_MAPPING
    VALIDATING = c.POSTURE_VALIDATING
    ACTIVE = c.POSTURE_ACTIVE
    RESTRICTED = c.POSTURE_RESTRICTED
    SUSPENDED = c.POSTURE_SUSPENDED


class VehicleStatus(str, Enum):
    DRAFT = c.VEHICLE_DRAFT
    IN_SERVICE = c.VEHICLE_IN_SERVICE
    AT_DEPOT = c.VEHICLE_AT_DEPOT
    ROADSIDE = c.VEHICLE_ROADSIDE
    SUSPENDED = c.VEHICLE_SUSPENDED


class VehicleServiceStatus(str, Enum):
    UNAVAILABLE = c.SERVICE_UNAVAILABLE
    AVAILABLE = c.SERVICE_AVAILABLE
    DISPATCHED = c.SERVICE_DISPATCHED
    ON_TRIP = c.SERVICE_ON_TRIP


class DepotPosture(str, Enum):
    OPEN = c.DEPOT_OPEN
    CONGESTED = c.DEPOT_CONGESTED
    LOCKDOWN = c.DEPOT_LOCKDOWN


class BaySlotStatus(str, Enum):
    RESERVED = c.SLOT_RESERVED
    ACTIVE = c.SLOT_ACTIVE
    COMPLETED = c.SLOT_COMPLETED
    RELEASED = c.SLOT_RELEASED


class CycleStatus(str, Enum):
    STAGED = c.CYCLE_STAGED
    IN_PROGRESS = c.CYCLE_IN_PROGRESS
    COMPLETED = c.CYCLE_COMPLETED
    ABORTED = c.CYCLE_ABORTED


class RideStatus(str, Enum):
    REQUESTED = c.RIDE_REQUESTED
    MATCHED = c.RIDE_MATCHED
    PICKED_UP = c.RIDE_PICKED_UP
    COMPLETED = c.RIDE_COMPLETED
    CANCELLED_NO_SHOW = c.RIDE_CANCELLED_NO_SHOW
    CANCELLED = c.RIDE_CANCELLED
    FAILED = c.RIDE_FAILED


class SessionStatus(str, Enum):
    ESCALATED = c.SESSION_ESCALATED
    ACKNOWLEDGED = c.SESSION_ACKNOWLEDGED
    RESOLVED = c.SESSION_RESOLVED
    UNRESOLVED = c.SESSION_UNRESOLVED


class IncidentStatus(str, Enum):
    FILED = c.INCIDENT_FILED
    UNDER_REVIEW = c.INCIDENT_UNDER_REVIEW
    CLOSED = c.INCIDENT_CLOSED
    VOIDED = c.INCIDENT_VOIDED


class RoadsideCaseStatus(str, Enum):
    OPEN = c.CASE_OPEN
    TEAM_ASSIGNED = c.CASE_TEAM_ASSIGNED
    RESPONSE_DISPATCHED = c.CASE_RESPONSE_DISPATCHED
    CLEARED = c.CASE_CLEARED
    CANCELLED = c.CASE_CANCELLED


class RoadsideTeamStatus(str, Enum):
    AVAILABLE = c.TEAM_AVAILABLE
    ON_CASE = c.TEAM_ON_CASE
    OFF_SHIFT = c.TEAM_OFF_SHIFT


class WaveStatus(str, Enum):
    PLANNED = c.WAVE_PLANNED
    ACTIVE = c.WAVE_ACTIVE
    COMPLETED = c.WAVE_COMPLETED
    ABORTED = c.WAVE_ABORTED


# ─── Entity payload shapes ────────────────────────────────────────────────


class ServiceTerritory(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    posture: str
    mapped_pct: int
    validation_hours: int
    road_type_risk: str
    active_zone_count: int
    total_credit_cents: int
    total_severe_incidents: int
    created_at: str
    updated_at: str
    version: int


class DepotSite(TypedDict, total=False):
    id: str
    territory_id: str
    name: str
    charge_positions: int
    cleaning_positions: int
    calib_positions: int
    software_positions: int
    posture: str
    occupancy_pct: int
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    territory_id: str
    vin: str
    status: str
    service_status: str
    battery_pct: int
    cleanliness_score: int
    calib_valid: bool
    software_version: str
    target_software_version: str
    credit_cents: int
    is_roadside_blocked: bool
    current_depot_id: Optional[str]
    delay_ops_runs: int
    created_at: str
    updated_at: str
    version: int


class BaySlot(TypedDict, total=False):
    id: str
    depot_id: str
    service_type: str
    bay_index: int
    start_utc: str
    duration_seconds: int
    end_utc: str
    vehicle_id: str
    cycle_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DepotCycle(TypedDict, total=False):
    id: str
    depot_id: str
    vehicle_id: str
    service_kind: str
    status: str
    is_scheduled: bool
    last_ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class DeploymentWave(TypedDict, total=False):
    id: str
    territory_id: str
    window_code: str
    planned_vehicle_count: int
    deployed_vehicle_count: int
    status: str
    last_ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class DemandSignal(TypedDict, total=False):
    id: str
    territory_id: str
    window_code: str
    projected_rides: int
    manual_only_rides: int
    effective_demand: int
    created_at: str
    updated_at: str
    version: int


class ServiceAreaRule(TypedDict, total=False):
    id: str
    territory_id: str
    rule_version: int
    route_class: str
    allowed: bool
    notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExclusionZone(TypedDict, total=False):
    id: str
    territory_id: str
    kind: str
    route_class: str
    start_utc: str
    duration_seconds: int
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAreaExpansionRequest(TypedDict, total=False):
    id: str
    territory_id: str
    target_region_code: str
    mapped_pct_at_submit: int
    rule_version_at_approval: Optional[int]
    status: str
    requires_road_type_validation: bool
    created_at: str
    updated_at: str
    version: int


class RideRequest(TypedDict, total=False):
    id: str
    territory_id: str
    rider_name: str
    sub_service_type: str
    manual_only_reason: Optional[str]
    status: str
    vehicle_id: Optional[str]
    pickup_location_id: Optional[str]
    dropoff_location_id: Optional[str]
    dispatch_attempts: int
    idempotency_key: str
    created_at: str
    updated_at: str
    version: int


class PickupLocation(TypedDict, total=False):
    id: str
    territory_id: str
    curb_segment_code: str
    curb_access: str
    is_valid: bool
    created_at: str
    updated_at: str
    version: int


class CurbRule(TypedDict, total=False):
    id: str
    territory_id: str
    curb_access: str
    sub_service_type: str
    allowed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AssistanceSession(TypedDict, total=False):
    id: str
    ride_request_id: str
    vehicle_id: str
    reason: str
    status: str
    escalation_tier: int
    attempt_count: int
    op_user_id: Optional[str]
    last_ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict, total=False):
    id: str
    assistance_session_id: str
    vehicle_id: str
    severity: str
    description: str
    status: str
    crash_evidence_retained: bool
    retention_expires_at: str
    created_at: str
    updated_at: str
    version: int


class RoadsideCase(TypedDict, total=False):
    id: str
    territory_id: str
    vehicle_id: str
    assistance_session_id: Optional[str]
    road_class: str
    status: str
    team_id: Optional[str]
    dispatched_at: Optional[str]
    raise_count: int
    created_ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class RoadsideTeam(TypedDict, total=False):
    id: str
    territory_id: str
    team_code: str
    road_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


ENTITY_NAMES: List[str] = [
    "ServiceTerritory",
    "DepotSite",
    "Vehicle",
    "BaySlot",
    "DepotCycle",
    "DeploymentWave",
    "DemandSignal",
    "ServiceAreaRule",
    "ExclusionZone",
    "ServiceAreaExpansionRequest",
    "RideRequest",
    "PickupLocation",
    "CurbRule",
    "AssistanceSession",
    "IncidentReport",
    "RoadsideCase",
    "RoadsideTeam",
]