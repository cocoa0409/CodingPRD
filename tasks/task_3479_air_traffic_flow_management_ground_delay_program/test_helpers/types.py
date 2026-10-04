"""Domain types: entity TypedDicts, status enums, and the role enum.

Every enum member is a literal the PRD declares. Four record types -
TMIRevision, SlotTransaction, CompressionRun and RerouteAssignment - are
append-only: they carry only ``id`` and ``created_at`` and never expose
``updated_at`` or ``version`` (PRD §2.4), so their TypedDicts omit those keys.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ── Enumerations ───────────────────────────────────────────────────────────

class UserRole(str, Enum):
    SYSTEM_ADMINISTRATOR = "SystemAdministrator"
    FLOW_MANAGER = "FlowManager"
    COMMAND_CENTER_ADMIN = "CommandCenterAdmin"
    OPERATOR = "Operator"


class FacilityType(str, Enum):
    AIRPORT = "AIRPORT"
    EN_ROUTE_SECTOR = "EN_ROUTE_SECTOR"


class FacilityStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    OUTAGE = "OUTAGE"


class OperatorType(str, Enum):
    SCHEDULED_CARRIER = "SCHEDULED_CARRIER"
    GENERAL_AVIATION = "GENERAL_AVIATION"
    UNSCHEDULED_CHARTER = "UNSCHEDULED_CHARTER"


class ConstraintEventType(str, Enum):
    WEATHER = "WEATHER"
    STAFFING = "STAFFING"
    EQUIPMENT = "EQUIPMENT"


class ConstraintEventStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    CLEARED = "CLEARED"


class ForecastVariant(str, Enum):
    PLANNING = "PLANNING"
    OPERATIONAL = "OPERATIONAL"


class ForecastStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    STALE = "STALE"


class TmiType(str, Enum):
    GROUND_DELAY_PROGRAM = "GROUND_DELAY_PROGRAM"
    GROUND_STOP = "GROUND_STOP"
    AIRSPACE_FLOW_PROGRAM = "AIRSPACE_FLOW_PROGRAM"
    REROUTE = "REROUTE"


class TmiStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PUBLISHED = "PUBLISHED"
    ACTIVE = "ACTIVE"
    REVISING = "REVISING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RevisionOrigin(str, Enum):
    MANUAL = "MANUAL"
    SYSTEM_AUTO_DOWNGRADE = "SYSTEM_AUTO_DOWNGRADE"


class FlightOpsStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AIRBORNE = "AIRBORNE"
    LANDED = "LANDED"
    CANCELLED = "CANCELLED"


class FlightControlStatus(str, Enum):
    UNCONTROLLED = "UNCONTROLLED"
    SLOTTED = "SLOTTED"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class SlotTransactionType(str, Enum):
    INITIAL_ASSIGNMENT = "INITIAL_ASSIGNMENT"
    SUBSTITUTION_SWAP = "SUBSTITUTION_SWAP"
    COMPRESSION_MOVE = "COMPRESSION_MOVE"
    RELEASE = "RELEASE"
    GA_ASSIGNMENT = "GA_ASSIGNMENT"
    REVISION_MOVE = "REVISION_MOVE"
    REVERSAL = "REVERSAL"


class GaPriorityClass(str, Enum):
    HIGH_PRIORITY = "HIGH_PRIORITY"
    STANDARD = "STANDARD"


class GaRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCOMMODATED = "ACCOMMODATED"
    WAITLISTED = "WAITLISTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


# ── Entity shapes (common_fields: id, created_at, updated_at, version) ─────

class Facility(TypedDict):
    id: str
    ident: str
    facility_type: str
    base_acceptance_rate: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict):
    id: str
    name: str
    operator_type: str
    cdm_member: bool
    cumulative_delay_minutes: int
    created_at: str
    updated_at: str
    version: int


class ConstraintEvent(TypedDict):
    id: str
    facility_id: str
    event_type: str
    severity: int
    window_start: str
    window_end: str
    extension_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityForecast(TypedDict):
    id: str
    facility_id: str
    variant: str
    window_start: str
    window_end: str
    included_event_ids: List[str]
    predicted_acceptance_rate: int
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrafficManagementInitiative(TypedDict):
    id: str
    facility_id: str
    tmi_type: str
    program_start: str
    program_end: str
    controlled_rate: int
    status: str
    proposed_by_user_id: str
    published_by_user_id: Optional[str]
    revision_count: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Flight(TypedDict):
    id: str
    operator_id: str
    designator: str
    origin: str
    arrival_facility_id: str
    scheduled_arrival: str
    estimated_arrival: str
    controlled_arrival: Optional[str]
    last_eta_reported_at: str
    ops_status: str
    control_status: str
    is_overflow: bool
    provisional_delay_minutes: int
    final_delay_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ArrivalSlot(TypedDict):
    id: str
    tmi_id: str
    slot_index: int
    slot_time: str
    is_ga_reserved: bool
    assigned_flight_id: Optional[str]
    original_flight_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GAAccommodationRequest(TypedDict):
    id: str
    operator_id: str
    tmi_id: str
    requested_window_start: str
    requested_window_end: str
    priority_class: str
    status: str
    accommodated_flight_id: Optional[str]
    accommodated_slot_time: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OperatorDelayLedger(TypedDict):
    id: str
    operator_id: str
    tmi_id: str
    flight_count: int
    attributed_delay_minutes: int
    reversed_delay_minutes: int
    fair_share_minutes: int
    deviation_minutes: int
    created_at: str
    updated_at: str
    version: int


# ── Append-only record types (PRD §2.4: only id and created_at) ────────────

class TMIRevision(TypedDict):
    id: str
    tmi_id: str
    revision_index: int
    previous_controlled_rate: Optional[int]
    new_controlled_rate: Optional[int]
    previous_program_end: Optional[str]
    new_program_end: Optional[str]
    origin: str
    reason: str
    applied: bool
    applied_at: Optional[str]
    created_at: str


class SlotTransaction(TypedDict):
    id: str
    tmi_id: str
    slot_id: Optional[str]
    flight_id: str
    operator_id: str
    transaction_type: str
    from_slot_time: Optional[str]
    to_slot_time: Optional[str]
    delay_delta_minutes: int
    note: Optional[str]
    created_at: str


class CompressionRun(TypedDict):
    id: str
    tmi_id: str
    released_slot_count: int
    moves_made: int
    passes_executed: int
    promoted_ga_request_ids: List[str]
    remaining_open_slots: int
    created_at: str


class RerouteAssignment(TypedDict):
    id: str
    tmi_id: str
    flight_id: str
    via_sector_id: str
    assigned_route: str
    hourly_bucket: str
    created_at: str
