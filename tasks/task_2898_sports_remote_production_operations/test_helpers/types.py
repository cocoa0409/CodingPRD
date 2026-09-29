"""Domain types for the Broadcast Operations API: status enums, role enum, entity shapes."""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PRODUCTION_MANAGER = "ProductionManager"
    TECHNICAL_DIRECTOR = "TechnicalDirector"
    LEAGUE_OPERATIONS = "LeagueOperations"
    UNION_STEWARD = "UnionSteward"
    CREW_MEMBER = "CrewMember"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class EventTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class VenueRoofType(str, Enum):
    OPEN = "OPEN"
    DOMED = "DOMED"
    RETRACTABLE = "RETRACTABLE"


class ProductionStatus(str, Enum):
    PLANNED = "PLANNED"
    SURVEYED = "SURVEYED"
    PROVISIONED = "PROVISIONED"
    REHEARSED = "REHEARSED"
    ON_AIR = "ON_AIR"
    WRAPPED = "WRAPPED"
    SETTLED = "SETTLED"


class TruckStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    IN_TRANSIT = "IN_TRANSIT"
    IN_MAINTENANCE = "IN_MAINTENANCE"


class SurveyStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class CameraPositionType(str, Enum):
    HARD = "HARD"
    HANDHELD = "HANDHELD"
    ROBO = "ROBO"
    AERIAL = "AERIAL"


class PathType(str, Enum):
    SATELLITE = "SATELLITE"
    FIBER = "FIBER"


class RedundancyClass(str, Enum):
    PRIMARY_ELIGIBLE = "PRIMARY_ELIGIBLE"
    BACKUP_ONLY = "BACKUP_ONLY"


class BookingRole(str, Enum):
    PRIMARY = "PRIMARY"
    BACKUP = "BACKUP"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    TEST_SCHEDULED = "TEST_SCHEDULED"
    TEST_FAILED = "TEST_FAILED"
    CONFIRMED = "CONFIRMED"
    FAILED_OVER = "FAILED_OVER"
    PROMOTED = "PROMOTED"
    RELEASED = "RELEASED"


#: The five statuses whose bookings contribute to a path's conserved aggregates.
ACTIVE_BOOKING_STATUSES = [
    BookingStatus.RESERVED.value,
    BookingStatus.TEST_SCHEDULED.value,
    BookingStatus.TEST_FAILED.value,
    BookingStatus.CONFIRMED.value,
    BookingStatus.PROMOTED.value,
]


class CrewPosition(str, Enum):
    TD = "TD"
    EIC = "EIC"
    A1 = "A1"
    CAM_OP = "CAM_OP"
    REPLAY_OP = "REPLAY_OP"
    GRAPHICS_OP = "GRAPHICS_OP"
    STATS_OP = "STATS_OP"
    UTILITY = "UTILITY"


class EmploymentType(str, Enum):
    STAFF = "STAFF"
    FREELANCE = "FREELANCE"


class CrewCallStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class FeedKind(str, Enum):
    LIVE_STATS = "LIVE_STATS"
    OFFICIAL_SCORING = "OFFICIAL_SCORING"
    PLAYER_TRACKING = "PLAYER_TRACKING"


class FeedStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SystemKind(str, Enum):
    GRAPHICS = "GRAPHICS"
    STATS = "STATS"
    REPLAY = "REPLAY"


class PrepStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"


class RehearsalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class RehearsalOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class AirStatus(str, Enum):
    PRE_SHOW = "PRE_SHOW"
    ON_AIR = "ON_AIR"
    IN_EXTENDED_PLAY = "IN_EXTENDED_PLAY"
    OFF_AIR = "OFF_AIR"


class SignalStatus(str, Enum):
    NOMINAL = "NOMINAL"
    ON_BACKUP = "ON_BACKUP"
    LOST = "LOST"


class IncidentKind(str, Enum):
    WEATHER_HOLD = "WEATHER_HOLD"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    EXTENDED_PLAY = "EXTENDED_PLAY"
    PATH_LOSS = "PATH_LOSS"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class CallResponseDecision(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class TestOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# ---------------------------------------------------------------------------
# Entity shapes
#
# Every entity below carries updated_at and version except CameraPosition and
# Incident, which are append-only log rows carrying only id and created_at.
# ---------------------------------------------------------------------------
class ProductionTruck(TypedDict):
    id: str
    truck_code: str
    tier_rating: str
    camera_channel_capacity: int
    power_draw_amps: int
    home_base_code: str
    engine_hours_since_service: int
    service_interval_hours: int
    hours_to_service: int
    last_service_completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Production(TypedDict):
    id: str
    event_tier: str
    league_code: str
    venue_name: str
    venue_power_capacity_amps: int
    venue_roof_type: str
    venue_curfew_utc: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    labor_budget_total_cents: int
    status: str
    truck_id: Optional[str]
    required_crew_positions: int
    required_validated_preps: int
    labor_committed_cents: int
    labor_available_cents: int
    labor_variance_cents: int
    settlement_total_cents: Optional[int]
    overrun_fee_cents: int
    readiness_score_preflight: float
    readiness_score_certified: float
    wrapped_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VenueSurvey(TypedDict):
    id: str
    production_id: str
    surveyor_name: str
    fiber_drops_required: int
    status: str
    revision: int
    camera_position_count: int
    total_cable_run_feet: int
    total_power_draw_amps: int
    power_headroom_amps: int
    total_signal_loss_db: float
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CameraPosition(TypedDict):
    """Append-only plot row: no updated_at, no version."""

    id: str
    survey_id: str
    label: str
    position_type: str
    cable_run_feet: int
    power_draw_amps: int
    signal_loss_db: float
    requires_operator: bool
    created_at: str


class TransmissionPath(TypedDict):
    id: str
    path_code: str
    path_type: str
    carrier_code: str
    capacity_mbps: int
    guard_band_minutes: int
    redundancy_class: str
    committed_mbps_total: int
    active_booking_count: int
    created_at: str
    updated_at: str
    version: int


class PathBooking(TypedDict):
    id: str
    production_id: str
    path_id: str
    booking_role: str
    window_start_utc: str
    window_end_utc: str
    requested_mbps: int
    status: str
    test_window_start_utc: Optional[str]
    test_window_end_utc: Optional[str]
    test_attempt_count: int
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict):
    id: str
    full_name: str
    position: str
    employment_type: str
    union_local: str
    certified_tiers: List[str]
    hourly_rate_cents: int
    home_base_code: str
    lifetime_meal_penalty_units: int
    created_at: str
    updated_at: str
    version: int


class CrewCall(TypedDict):
    id: str
    production_id: str
    crew_member_id: str
    call_time_utc: str
    scheduled_release_utc: str
    actual_release_utc: Optional[str]
    meal_break_start_utc: Optional[str]
    offer_rate_cents: Optional[int]
    effective_rate_cents: int
    status: str
    provisional_total_cents: int
    settled_total_cents: Optional[int]
    meal_penalty_units: int
    turnaround_minutes_before_call: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DataFeed(TypedDict):
    id: str
    provider_code: str
    feed_kind: str
    latency_ms: int
    contract_expiry_utc: str
    max_concurrent_consumers: int
    status: str
    active_consumer_count: int
    created_at: str
    updated_at: str
    version: int


class SystemPrep(TypedDict):
    id: str
    production_id: str
    data_feed_id: str
    system_kind: str
    replay_channel_count: Optional[int]
    status: str
    feed_validated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Rehearsal(TypedDict):
    id: str
    production_id: str
    scheduled_start_utc: str
    status: str
    camera_blocking_positions_cleared: Optional[int]
    venue_signoff: Optional[bool]
    league_ops_signoff: Optional[bool]
    outcome_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShowExecution(TypedDict):
    id: str
    production_id: str
    air_status: str
    signal_status: str
    readiness_hold: bool
    weather_hold_minutes: int
    extended_play_minutes: int
    technical_downtime_minutes: int
    air_minutes_total: int
    on_air_at_utc: Optional[str]
    off_air_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    """Append-only contingency log row: no updated_at, no version."""

    id: str
    show_execution_id: str
    kind: str
    started_at_utc: str
    duration_minutes: int
    severity: str
    note: Optional[str]
    created_at: str


#: Entities that carry updated_at and version (PRD 2.4).
VERSIONED_ENTITIES = [
    "ProductionTruck",
    "Production",
    "VenueSurvey",
    "TransmissionPath",
    "PathBooking",
    "CrewMember",
    "CrewCall",
    "DataFeed",
    "SystemPrep",
    "Rehearsal",
    "ShowExecution",
]

#: Append-only entities that carry only id and created_at (PRD 2.4).
APPEND_ONLY_ENTITIES = ["CameraPosition", "Incident"]
