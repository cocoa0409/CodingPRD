"""Domain types: entity TypedDicts, status enums, role enum.

Field names are taken verbatim from the PRD. Entities that are created once and
never modified in place (``OpsRun`` and ``ServiceFailureClaim``) carry only
``id`` and ``created_at``; every other resource additionally carries
``updated_at`` and ``version``.
"""
from enum import Enum
from typing import Optional, TypedDict


class HubPosture(str, Enum):
    OPEN = "OPEN"
    CONGESTED = "CONGESTED"
    LOCKDOWN = "LOCKDOWN"
    GROUND_STOP = "GROUND_STOP"


class ArrivalBankStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    UNLOADING = "UNLOADING"
    UNLOADED = "UNLOADED"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class AircraftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_FLIGHT = "IN_FLIGHT"
    LANDED = "LANDED"
    UNLOADING = "UNLOADING"
    UNLOADED = "UNLOADED"
    CANCELLED = "CANCELLED"


class CommodityClass(str, Enum):
    GENERAL = "GENERAL"
    IRREGULAR = "IRREGULAR"
    HAZMAT = "HAZMAT"
    PERISHABLE = "PERISHABLE"


class ServiceLevel(str, Enum):
    NEXT_DAY_AIR = "NEXT_DAY_AIR"
    SECOND_DAY_AIR = "SECOND_DAY_AIR"
    GROUND = "GROUND"


class InductionStatus(str, Enum):
    NOT_INDUCTED = "NOT_INDUCTED"
    INDUCTED = "INDUCTED"
    REJECTED = "REJECTED"


class SortStatus(str, Enum):
    UNSORTED = "UNSORTED"
    PRIMARY_SORTED = "PRIMARY_SORTED"
    SECONDARY_SORTED = "SECONDARY_SORTED"
    LOADED = "LOADED"


class CommitmentStatus(str, Enum):
    COMMITTED = "COMMITTED"
    DOWNGRADED = "DOWNGRADED"
    REROUTED = "REROUTED"
    VOIDED = "VOIDED"
    UPGRADED_HELD = "UPGRADED_HELD"


class HandlingStatus(str, Enum):
    NORMAL = "NORMAL"
    ROUTED_TO_IRREGULAR = "ROUTED_TO_IRREGULAR"
    ROUTED_TO_HAZMAT = "ROUTED_TO_HAZMAT"
    DIVERTED = "DIVERTED"
    HOLD_AT_HUB = "HOLD_AT_HUB"


class HandlingPosture(str, Enum):
    STANDARD = "STANDARD"
    IRREGULAR_LANE = "IRREGULAR_LANE"
    HAZMAT_LANE = "HAZMAT_LANE"


class CommitmentPosture(str, Enum):
    COMMITTED_OK = "COMMITTED_OK"
    DOWNGRADE_PENDING = "DOWNGRADE_PENDING"
    REROUTE_PENDING = "REROUTE_PENDING"


class LaneKind(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    IRREGULAR = "IRREGULAR"
    HAZMAT = "HAZMAT"


class LaneStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SATURATED = "SATURATED"
    CLOSED = "CLOSED"


class LoadMoveStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    LOADING = "LOADING"
    LOADED = "LOADED"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    CANCELLED = "CANCELLED"


class BuildupStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    WEIGHT_BREACH = "WEIGHT_BREACH"
    CANCELLED = "CANCELLED"


class LoadPlanTier(str, Enum):
    UNDER_CAPACITY = "UNDER_CAPACITY"
    AT_CAPACITY = "AT_CAPACITY"
    RESERVE_TIER = "RESERVE_TIER"


class FeederStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    STAGING = "STAGING"
    LOADING = "LOADING"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OVERRUN = "OVERRUN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StaffingPosture(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"
    SATURATED = "SATURATED"


class OpsRunLevel(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class OpsRunVerdict(str, Enum):
    ADVANCED = "ADVANCED"
    HELD = "HELD"
    RELEASED = "RELEASED"


class CauseCode(str, Enum):
    LATE_INBOUND = "LATE_INBOUND"
    SORT_MISS = "SORT_MISS"
    WEATHER = "WEATHER"
    MECHANICAL = "MECHANICAL"
    NO_SCAN = "NO_SCAN"
    BAD_ADDRESS = "BAD_ADDRESS"
    REVENUE_PRORATE = "REVENUE_PRORATE"


class AttributedRole(str, Enum):
    CARRIER = "CARRIER"
    CUSTOMER = "CUSTOMER"
    WEATHER_EVENT = "WEATHER_EVENT"
    MECHANICAL_EVENT = "MECHANICAL_EVENT"


class ServiceFailureStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    HUB_OPS_MANAGER = "HubOpsManager"
    SORT_SUPERVISOR = "SortSupervisor"
    SORT_OPERATOR = "SortOperator"
    LOAD_PLANNER = "LoadPlanner"
    COMMITMENT_CONTROLLER = "CommitmentController"
    FEEDER_COORDINATOR = "FeederCoordinator"
    GATEWAY_COORDINATOR = "GatewayCoordinator"
    HAZMAT_CERTIFIER = "HazmatCertifier"
    WEATHER_OFFICER = "WeatherOfficer"
    REFUND_ADJUSTER = "RefundAdjuster"


# ─── common_fields: true — id + created_at + updated_at + version ───────────


class Hub(TypedDict):
    id: str
    iata_code: str
    name: str
    sort_window_open_minutes: int
    sort_window_close_minutes: int
    alternate_hub_id: Optional[str]
    live_planned_package_total: int
    posture: str
    contingency_mode: bool
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class ArrivalBank(TypedDict):
    id: str
    hub_id: str
    bank_code: str
    scheduled_start_minutes: int
    scheduled_end_minutes: int
    actual_start_minutes: Optional[int]
    hydraulic_crew_available: bool
    status: str
    effective_sort_budget_minutes: int
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict):
    id: str
    bank_id: str
    tail_number: str
    origin_station_code: str
    scheduled_arrival_minutes: int
    actual_arrival_minutes: Optional[int]
    capacity_weight_grams: int
    inbound_weight_grams: Optional[int]
    unload_completed_minutes: Optional[int]
    maintenance_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict):
    id: str
    hub_id: str
    aircraft_id: str
    tracking_number: str
    acknowledgement_number: Optional[str]
    commodity_class: str
    destination_hub_code: str
    service_level: str
    commitment_cutoff_minutes: int
    planned_weight_grams: int
    rated_weight_grams: Optional[int]
    dimension_weight_grams: int
    induction_status: str
    sort_status: str
    commitment_status: str
    handling_status: str
    last_sort_minutes: Optional[int]
    buildup_id: Optional[str]
    assigned_lane_id: Optional[str]
    staged_feeder_id: Optional[str]
    handling_posture: str
    commitment_posture: str
    final_commitment_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SortLane(TypedDict):
    id: str
    hub_id: str
    lane_code: str
    lane_kind: str
    commodity_capability: str
    capacity_weight_grams: int
    certified_until_minutes: int
    turnout_start_minutes: int
    turnout_end_minutes: int
    status: str
    lane_load_grams: int
    created_at: str
    updated_at: str
    version: int


class LoadMove(TypedDict):
    id: str
    hub_id: str
    aircraft_id: str
    sequence: int
    status: str
    weight_limit_grams: int
    planned_weight_grams: int
    loaded_weight_grams: int
    forward_capacity_grams: int
    load_plan_tier: str
    gateway_requirements: dict
    created_at: str
    updated_at: str
    version: int


class Buildup(TypedDict):
    id: str
    load_move_id: str
    destination_gateway_code: str
    rated_weight_grams: int
    container_limit_grams: int
    hazardous_load: bool
    hazardous_weight_grams: int
    hazardous_cap_grams: int
    requires_container: bool
    status: str
    load_plan_tier: str
    created_at: str
    updated_at: str
    version: int


class GroundFeeder(TypedDict):
    id: str
    hub_id: str
    feeder_code: str
    origin_station_code: str
    scheduled_departure_minutes: int
    stage_capacity_grams: int
    window_minutes: int
    status: str
    staged_weight_grams: int
    created_at: str
    updated_at: str
    version: int


class LaborShift(TypedDict):
    id: str
    hub_id: str
    shift_code: str
    start_minutes: int
    end_minutes: int
    headcount: int
    productivity_grams_per_operator_hour: int
    forecast_volume_grams: int
    certified_for_hazmat: bool
    volume_variance_pct: float
    staffing_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceFailure(TypedDict):
    id: str
    hub_id: str
    package_id: str
    cause_code: str
    attributed_role: str
    failure_minutes: int
    refund_eligible: bool
    refund_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── common_fields: false — id + created_at only ────────────────────────────


class OpsRun(TypedDict):
    id: str
    hub_id: str
    run_index: int
    minute_of_day: int
    level: str
    verdict: str
    created_at: str


class ServiceFailureClaim(TypedDict):
    id: str
    service_failure_id: str
    claim_index: int
    outcome: str
    actor_role: str
    note: Optional[str]
    created_at: str