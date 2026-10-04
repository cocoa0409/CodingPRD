"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD exactly. Entities whose PRD contract carries the
four common resource properties (id, created_at, updated_at, version) list all
four; the append-only resources list only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class AuditoriumStatus(str, Enum):
    LIVE = "LIVE"
    TURNOVER = "TURNOVER"
    DARK = "DARK"


class BuildPhase(str, Enum):
    EMPTY = "EMPTY"
    SETUP = "SETUP"
    NEARLY_READY = "NEARLY_READY"
    READY = "READY"


class ShowtimeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DINING_OPEN = "DINING_OPEN"
    SERVICE = "SERVICE"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ShowtimeMode(str, Enum):
    DINING_OPEN = "DINING_OPEN"
    DINING_CLOSED = "DINING_CLOSED"


class ServiceMode(str, Enum):
    PRE_SHOW = "PRE_SHOW"
    IN_KITCHEN = "IN_KITCHEN"
    DARK_PERIOD = "DARK_PERIOD"


class ProgrammingEventStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVATED = "ACTIVATED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PreShowContentStatus(str, Enum):
    PRE_SHOW_DRAFT = "PRE_SHOW_DRAFT"
    PRE_SHOW_IN_REVIEW = "PRE_SHOW_IN_REVIEW"
    PRE_SHOW_APPROVED = "PRE_SHOW_APPROVED"
    PRE_SHOW_REJECTED = "PRE_SHOW_REJECTED"


class MenuChannel(str, Enum):
    ENTREE = "ENTREE"
    BEVERAGE = "BEVERAGE"


class AvailabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class ServerRosterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENALIZED = "PENALIZED"


class SectionAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REASSIGNMENT_PENDING = "REASSIGNMENT_PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderSlipStatus(str, Enum):
    PLACED = "PLACED"
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class IdCheckStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REFUSED = "REFUSED"


class KitchenStation(str, Enum):
    COLD_LINE = "cold_line"
    HOT_LINE = "hot_line"


class KitchenTicketStatus(str, Enum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    READY = "READY"
    DELIVERED = "DELIVERED"
    VOIDED = "VOIDED"


class CheckTabStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class RefundReasonCode(str, Enum):
    EJECTION_NO_TALKING = "EJECTION_NO_TALKING"
    EJECTION_NO_TEXTING = "EJECTION_NO_TEXTING"
    SERVICE_COMP_FAILURE = "SERVICE_COMP_FAILURE"
    SERVICE_DELAY = "SERVICE_DELAY"


class DisturbanceKind(str, Enum):
    NO_TALKING = "NO_TALKING"
    NO_TEXTING = "NO_TEXTING"


class DisturbanceStage(str, Enum):
    WARNING = "WARNING"
    FINAL_WARNING = "FINAL_WARNING"
    EJECTION = "EJECTION"


class CapacityBand(str, Enum):
    NORMAL = "NORMAL"
    LATE = "LATE"
    BLOCKED = "BLOCKED"


class ProjectionVariant(str, Enum):
    WAVE_PROJECTION = "wave_projection"
    FINAL_PROJECTION = "final_projection"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    KITCHEN_LEAD = "KitchenLead"
    SERVER = "Server"
    PROGRAMMING_COORDINATOR = "ProgrammingCoordinator"
    PRE_SHOW_PRODUCER = "PreShowProducer"
    ANONYMOUS = "Anonymous"


# common_fields: true — carries id + created_at + updated_at + version
class Auditorium(TypedDict):
    id: str
    name: str
    seat_capacity: int
    screen_lead_time_minutes: int
    kitchen_point_rate: int
    alcove_point_rate: int
    status: str
    service_posture: str
    build_phase: str
    last_showtime_cluster_start_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Showtime(TypedDict):
    id: str
    auditorium_id: str
    title: str
    start_at_utc: str
    runtime_minutes: int
    content_type: str
    pre_show_minutes: int
    status: str
    dining_open_at_utc: str
    entree_ready_deadline_utc: str
    dining_close_at_utc: str
    service_mode: str
    mode: str
    created_at: str
    updated_at: str
    version: int


class ProgrammingEvent(TypedDict):
    id: str
    auditorium_id: str
    theme_name: str
    requires_themed_menu: bool
    pre_show_content_status: str
    status: str
    pre_show_content_version: int
    themed_menu_count: int
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    catalog_name: str
    channel: str
    price_cents: int
    prep_minutes: int
    is_alcoholic: bool
    availability_state: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only attachment, ONLY id + created_at
class ThemedMenuItem(TypedDict):
    id: str
    programming_event_id: str
    menu_item_id: str
    theme_price_cents: int
    is_signature: bool
    created_at: str


class Server(TypedDict):
    id: str
    display_name: str
    home_auditorium_id: str
    ratings: List[dict]
    lifetime_points: int
    in_rotation: bool
    shift_load_projected: int
    shift_load_final: int
    rollup_provisional_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SectionAssignment(TypedDict):
    id: str
    showtime_id: str
    auditorium_id: str
    server_id: str
    section_label: str
    status: str
    version: int
    assignment_points: int
    created_at: str
    updated_at: str


class OrderSlip(TypedDict):
    id: str
    showtime_id: str
    section_assignment_id: str
    seat_number: int
    status: str
    channel: str
    placement_mode: str
    placed_at_utc: str
    in_kitchen_at_utc: Optional[str]
    delivered_at_utc: Optional[str]
    lines: List[dict]
    resolved_lines: List[dict]
    subtotal_cents: int
    id_check_required: bool
    id_check_status: str
    created_at: str
    updated_at: str
    version: int


class KitchenTicket(TypedDict):
    id: str
    showtime_id: str
    order_slip_id: str
    station: str
    point_cost: int
    fire_at_utc: str
    projected_delivery_at_utc: str
    status: str
    sequence_position: int
    overflow_reason: Optional[str]
    allergen_substitution: bool
    created_at: str
    updated_at: str
    version: int


class CheckTab(TypedDict):
    id: str
    order_slip_id: str
    status: str
    original_cents: int
    refunded_cents: int
    reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only report, ONLY id + created_at
class DisturbanceEvent(TypedDict):
    id: str
    order_slip_id: str
    kind: str
    stage: str
    prior_stage: Optional[str]
    stage_version: int
    occurred_at_utc: str
    ejected_occupant_id: Optional[str]
    created_at: str