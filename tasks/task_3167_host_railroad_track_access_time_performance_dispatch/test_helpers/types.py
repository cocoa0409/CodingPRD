"""Domain types: entity shapes, status enums, and the role enum.

Every resource carries the common fields of the PRD's common-resource section:
``id``, ``created_at``, ``updated_at`` and ``version``. Status values below are
the declared members of each entity's lifecycle.
"""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    PASSENGER_OPERATOR = "PassengerOperator"
    HOST_RAILROAD_REP = "HostRailroadRep"
    STATE_SPONSOR = "StateSponsor"


class CorridorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TrackClass(str, Enum):
    SINGLE = "SINGLE"
    DOUBLE = "DOUBLE"


class TrackSegmentStatus(str, Enum):
    OPERABLE = "OPERABLE"
    CAPITAL_HOLD = "CAPITAL_HOLD"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class TimetableStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RATIFIED = "RATIFIED"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"


class TrainRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DISRUPTED = "DISRUPTED"


class CancellationReason(str, Enum):
    OPERATOR_CANCEL = "OPERATOR_CANCEL"
    AGREEMENT_SUSPENDED = "AGREEMENT_SUSPENDED"
    DISRUPTION = "DISRUPTION"


class PassageStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTUALIZED = "ACTUALIZED"
    SKIPPED = "SKIPPED"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"
    REVERSED = "REVERSED"


class IncidentCause(str, Enum):
    HOST_FREIGHT_HOLD = "HOST_FREIGHT_HOLD"
    HOST_SIGNAL = "HOST_SIGNAL"
    HOST_TRACK = "HOST_TRACK"
    MECHANICAL = "MECHANICAL"
    STATION_DWELL = "STATION_DWELL"
    WEATHER = "WEATHER"
    DISRUPTION = "DISRUPTION"


class IncidentOrigin(str, Enum):
    CODED = "CODED"
    SYSTEM_DISRUPTION = "SYSTEM_DISRUPTION"


class DisputeStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class DisputeResolution(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class ProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    FUNDED = "FUNDED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"


class ProjectType(str, Enum):
    SIDING = "SIDING"
    SIGNAL = "SIGNAL"
    DOUBLE_TRACK = "DOUBLE_TRACK"


class WindowStatus(str, Enum):
    PLANNED = "PLANNED"
    LOCKED = "LOCKED"
    RELEASED = "RELEASED"


class DisruptionStatus(str, Enum):
    OPEN = "OPEN"
    BRIDGED = "BRIDGED"
    RECOVERED = "RECOVERED"


class FundingStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    SETTLED = "SETTLED"


class ComputationVariant(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    REISSUED = "REISSUED"
    PAID = "PAID"


class HostRailroad(TypedDict, total=False):
    id: str
    name: str
    reporting_mark: str
    created_at: str
    updated_at: str
    version: int


class Corridor(TypedDict, total=False):
    id: str
    host_railroad_id: str
    code: str
    name: str
    endpoint_a: str
    endpoint_b: str
    service_type: str
    annual_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrackSegment(TypedDict, total=False):
    id: str
    corridor_id: str
    sequence_no: int
    milepost_start: float
    milepost_end: float
    state_code: str
    track_class: str
    capacity_trains_per_day: int
    pure_run_minutes: int
    dwell_after_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OperatingAgreement(TypedDict, total=False):
    id: str
    host_railroad_id: str
    corridor_id: str
    effective_from: str
    effective_to: str
    on_time_threshold_minutes: int
    penalty_rate_cents_per_minute: int
    incentive_rate_cents_per_train_mile: int
    otp_target_pct: float
    running_time_allowance_pct: float
    status: str
    amendment_seq: int
    created_at: str
    updated_at: str
    version: int


class Timetable(TypedDict, total=False):
    id: str
    corridor_id: str
    operating_agreement_id: str
    service_date_start: str
    service_date_end: str
    trains_per_day: int
    departure_time_of_day: str
    headway_minutes: int
    status: str
    revision_no: int
    created_at: str
    updated_at: str
    version: int


class TrainRun(TypedDict, total=False):
    id: str
    timetable_id: str
    train_number: str
    service_date: str
    scheduled_departure_at: str
    scheduled_arrival_at: str
    actual_departure_at: Optional[str]
    actual_arrival_at: Optional[str]
    origin_departure_delay_minutes: Optional[int]
    destination_arrival_delay_minutes: Optional[int]
    on_time_endpoint: Optional[bool]
    on_time_all_stations: Optional[bool]
    attributed_host_delay_minutes: int
    cancellation_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SegmentPassage(TypedDict, total=False):
    id: str
    train_run_id: str
    track_segment_id: str
    segment_sequence_no: int
    planned_entry_at: str
    planned_exit_at: str
    actual_entry_at: Optional[str]
    actual_exit_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DelayIncident(TypedDict, total=False):
    id: str
    train_run_id: str
    segment_passage_id: Optional[str]
    cause_code: str
    delay_minutes: int
    host_attributable: bool
    origin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DispatchPriorityDispute(TypedDict, total=False):
    id: str
    delay_incident_id: str
    train_run_id: str
    reason: Optional[str]
    resolution: Optional[str]
    resolved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalProject(TypedDict, total=False):
    id: str
    operating_agreement_id: str
    track_segment_id: str
    project_type: str
    funded_amount_cents: int
    added_frequency_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict, total=False):
    id: str
    track_segment_id: str
    window_start_at: str
    window_end_at: str
    clearance_buffer_minutes: int
    equipment_unit_id: str
    window_hours: float
    equipment_week_hours_available: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceDisruption(TypedDict, total=False):
    id: str
    corridor_id: str
    disruption_type: str
    started_at: str
    cleared_at: Optional[str]
    reaccommodation_policy: str
    bus_bridge_active: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingAgreement(TypedDict, total=False):
    id: str
    corridor_id: str
    state_code: str
    period_start: str
    period_end: str
    allocated_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementStatement(TypedDict, total=False):
    id: str
    operating_agreement_id: str
    period_start: str
    period_end: str
    computation_variant: str
    completed_run_count: int
    train_miles: float
    otp_pct: Optional[float]
    host_delay_minutes: int
    penalty_cents: int
    incentive_cents: int
    net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
