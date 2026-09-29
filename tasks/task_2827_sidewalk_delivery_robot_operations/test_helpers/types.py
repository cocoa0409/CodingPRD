"""Domain types for the Sidewalk Delivery Robot Operations API.

Entity TypedDicts, lifecycle enums and the role enum, all named exactly as the
PRD names them. Every entity in this API carries the four common fields
(``id``, ``created_at``, ``updated_at``, ``version``).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FLEET_DISPATCHER = "FleetDispatcher"
    REMOTE_OPERATOR = "RemoteOperator"
    SAFETY_OFFICER = "SafetyOfficer"
    CUSTOMER_SUPPORT = "CustomerSupport"
    MERCHANT_OPERATOR = "MerchantOperator"


# --------------------------------------------------------------------------
# Lifecycle enums
# --------------------------------------------------------------------------

class PermitState(str, Enum):
    PROVISIONED = "PROVISIONED"
    PERMITTED = "PERMITTED"
    RESTRICTED = "RESTRICTED"
    REVOKED = "REVOKED"


class SegmentStatus(str, Enum):
    MAPPED = "MAPPED"
    SURVEYED = "SURVEYED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    RETIRED = "RETIRED"


class SegmentType(str, Enum):
    WALKWAY = "WALKWAY"
    CROSSING = "CROSSING"
    RAMP = "RAMP"


class CrossingControl(str, Enum):
    NONE = "NONE"
    SIGNALIZED = "SIGNALIZED"
    UNSIGNALIZED = "UNSIGNALIZED"
    MIDBLOCK = "MIDBLOCK"


class ClosureKind(str, Enum):
    HARD = "HARD"
    ADVISORY = "ADVISORY"


class ClosureCause(str, Enum):
    CONSTRUCTION = "CONSTRUCTION"
    WEATHER = "WEATHER"
    EVENT = "EVENT"
    VANDALISM = "VANDALISM"


class ClosureState(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class IntegrationState(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MerchantGrade(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"
    ANCHOR = "ANCHOR"


class DutyState(str, Enum):
    OFFLINE = "OFFLINE"
    STAGING = "STAGING"
    AVAILABLE = "AVAILABLE"
    ON_MISSION = "ON_MISSION"
    CHARGING = "CHARGING"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class HealthState(str, Enum):
    NOMINAL = "NOMINAL"
    DEGRADED = "DEGRADED"
    IMPAIRED = "IMPAIRED"
    QUARANTINED = "QUARANTINED"


class BayType(str, Enum):
    CHARGE = "CHARGE"
    STAGE = "STAGE"
    SERVICE = "SERVICE"


class BayState(str, Enum):
    OPEN = "OPEN"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ReservationType(str, Enum):
    CHARGE = "CHARGE"
    SERVICE = "SERVICE"
    STAGE = "STAGE"


class ReservationState(str, Enum):
    HELD = "HELD"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class OrderState(str, Enum):
    RECEIVED = "RECEIVED"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class PayloadTier(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class ExceptionReason(str, Enum):
    BLOCKED_ROUTE = "BLOCKED_ROUTE"
    WEATHER = "WEATHER"
    VANDALISM = "VANDALISM"
    ROBOT_FAULT = "ROBOT_FAULT"
    LATE = "LATE"


class RemedyKind(str, Enum):
    REFUND = "REFUND"
    REDELIVER = "REDELIVER"
    GOODWILL_CREDIT = "GOODWILL_CREDIT"


class MissionState(str, Enum):
    PLANNED = "PLANNED"
    LOADED = "LOADED"
    EN_ROUTE = "EN_ROUTE"
    BLOCKED = "BLOCKED"
    HANDOFF_READY = "HANDOFF_READY"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class AbortReason(str, Enum):
    ROBOT_QUARANTINED = "ROBOT_QUARANTINED"
    ZONE_REVOKED = "ZONE_REVOKED"
    DISPATCH_CANCELLED = "DISPATCH_CANCELLED"
    UNRECOVERABLE_BLOCKAGE = "UNRECOVERABLE_BLOCKAGE"


class PlanState(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class RejectionReason(str, Enum):
    OPERATOR_REJECTED = "OPERATOR_REJECTED"
    SEGMENT_BLOCKED = "SEGMENT_BLOCKED"
    REPLACED_BY_NEWER = "REPLACED_BY_NEWER"


class TakeoverState(str, Enum):
    REQUESTED = "REQUESTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    ESCALATED = "ESCALATED"


class TriggerReason(str, Enum):
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    PEDESTRIAN_CONFLICT = "PEDESTRIAN_CONFLICT"
    OBSTACLE = "OBSTACLE"
    CROSSING_ASSIST = "CROSSING_ASSIST"
    VANDALISM_ALERT = "VANDALISM_ALERT"


class ReportState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED_MUNICIPAL = "SUBMITTED_MUNICIPAL"
    INSURER_NOTIFIED = "INSURER_NOTIFIED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


class IncidentCategory(str, Enum):
    PEDESTRIAN_CONTACT = "PEDESTRIAN_CONTACT"
    RIGHT_OF_WAY_VIOLATION = "RIGHT_OF_WAY_VIOLATION"
    VANDALISM = "VANDALISM"
    OBSTRUCTION = "OBSTRUCTION"
    CLEARANCE_BREACH = "CLEARANCE_BREACH"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    CRITICAL = "CRITICAL"


# --------------------------------------------------------------------------
# Entity TypedDicts — every entity carries id / created_at / updated_at / version
# --------------------------------------------------------------------------

class ServiceZone(TypedDict):
    id: str
    name: str
    municipality_code: str
    permit_state: str
    ordinance_min_clearance_cm: float
    ordinance_max_speed_cm_s: int
    operating_window_start_utc_hhmm: str
    operating_window_end_utc_hhmm: str
    max_concurrent_robots: int
    max_crossing_risk: float
    takeover_confidence_threshold_pct: int
    planning_haul_m: float
    planning_crossings: int
    remedy_budget_cents: int
    remedy_spent_cents: int
    remedy_budget_remaining_cents: int
    reserved_bay_minutes: int
    open_incident_count: int
    on_mission_robot_count: int
    insurer_notify_threshold_cents: int
    lid_code_sequence: int
    restriction_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SidewalkSegment(TypedDict):
    id: str
    zone_id: str
    segment_code: str
    segment_type: str
    crossing_control: str
    length_m: float
    measured_clearance_cm: float
    surface_grade_pct: float
    sightline_m: float
    pedestrian_flow_per_min: float
    curb_ramp_present: bool
    crossing_risk_score: Optional[float]
    status: str
    connected_segment_ids: List[str]
    blocked_by_closure_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SegmentClosure(TypedDict):
    id: str
    segment_id: str
    closure_kind: str
    cause: str
    starts_at_utc: str
    ends_at_utc: str
    state: str
    reroute_triggered_count: int
    created_at: str
    updated_at: str
    version: int


class Merchant(TypedDict):
    id: str
    zone_id: str
    name: str
    handoff_sla_seconds: int
    merchant_grade: str
    integration_state: str
    escrowed_fee_cents: int
    recognized_fee_cents: int
    released_fee_cents: int
    settlement_variance_cents: int
    exception_count: int
    created_at: str
    updated_at: str
    version: int


class Robot(TypedDict):
    id: str
    zone_id: str
    asset_tag: str
    width_cm: float
    container_capacity_liters: float
    max_speed_cm_s: int
    battery_pct: float
    duty_state: str
    health_state: str
    odometer_m: float
    yield_event_count: int
    tamper_flag: bool
    lifetime_mission_count: int
    lifetime_intervention_count: int
    lifetime_escalation_count: int
    clean_mission_count: int
    rolling_autonomy_index: int
    lifetime_autonomy_index: int
    active_mission_id: Optional[str]
    current_bay_reservation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DepotBay(TypedDict):
    id: str
    zone_id: str
    bay_code: str
    bay_type: str
    power_kw: float
    committed_minutes: int
    state: str
    created_at: str
    updated_at: str
    version: int


class BayReservation(TypedDict):
    id: str
    bay_id: str
    robot_id: str
    reservation_type: str
    window_start_utc: str
    window_end_utc: str
    state: str
    window_minutes: int
    created_at: str
    updated_at: str
    version: int


class DeliveryOrder(TypedDict):
    id: str
    merchant_id: str
    dropoff_segment_id: str
    customer_ref: str
    payload_liters: float
    declared_value_cents: int
    promised_by_utc: str
    urgency_flag: bool
    payload_tier: str
    quoted_fee_cents: int
    settled_fee_cents: Optional[int]
    order_state: str
    exception_reason: Optional[str]
    remedy_kind: Optional[str]
    remedy_reason_code: Optional[str]
    remedy_amount_cents: Optional[int]
    dispatch_attempt_count: int
    created_at: str
    updated_at: str
    version: int


class DeliveryMission(TypedDict):
    id: str
    order_id: str
    robot_id: str
    mission_state: str
    lid_access_code: Optional[str]
    actual_payload_liters: Optional[float]
    handoff_late: bool
    active_route_plan_id: Optional[str]
    blocking_segment_id: Optional[str]
    traveled_distance_m: float
    traversed_crossing_count: int
    blocked_minutes: int
    intervention_count: int
    escalation_count: int
    active_minutes: int
    departed_at_utc: Optional[str]
    blocked_at_utc: Optional[str]
    completed_at_utc: Optional[str]
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoutePlan(TypedDict):
    id: str
    mission_id: str
    segment_sequence: List[str]
    plan_state: str
    total_length_m: float
    crossing_count: int
    clearance_margin_cm: float
    planned_duration_min: int
    revision_index: int
    supersedes_plan_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InterventionEvent(TypedDict):
    id: str
    mission_id: str
    trigger_reason: str
    autonomy_confidence_pct: int
    takeover_state: str
    mandatory: bool
    operator_user_id: Optional[str]
    control_seconds: int
    assumed_at_utc: Optional[str]
    escalation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    zone_id: str
    mission_id: Optional[str]
    robot_id: str
    category: str
    severity: str
    narrative: str
    estimated_damage_cents: int
    report_state: str
    filed_by_user_id: str
    reviewed_by_user_id: Optional[str]
    municipal_case_ref: Optional[str]
    insurer_claim_ref: Optional[str]
    insurer_notification_required: bool
    municipal_due_by_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ZoneEconomics(TypedDict):
    zone_id: str
    robot_active_minutes: int
    fleet_capacity_minutes: int
    utilization_pct: float
    allocated_overhead_cents: int
    variable_cost_cents: int
    delivered_count: int
    cost_per_delivery_cents: Optional[int]
    contribution_per_delivery_cents: Optional[int]
    throughput_per_robot_hour: float
