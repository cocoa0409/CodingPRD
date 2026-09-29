"""Domain types: role enum, status enums and entity TypedDicts.

Field lists are PRD-exact. Every persisted row carries ``id`` and ``created_at``;
almost every row additionally carries ``updated_at`` and ``version``. The one
exception is the checklist line, which "carries only `id` and `created_at`"
(PRD §2.5) — its TypedDict therefore omits ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --- Roles (PRD §2.1) -------------------------------------------------------
class UserRole(str, Enum):
    PARK_OPS_ADMIN = "ParkOpsAdmin"
    MAINTENANCE_MANAGER = "MaintenanceManager"
    MAINTENANCE_TECHNICIAN = "MaintenanceTechnician"
    QUALIFIED_INSPECTOR = "QualifiedInspector"
    SAFETY_OFFICER = "SafetyOfficer"
    RIDE_OPERATOR = "RideOperator"


# --- Enumerated attribute sets ----------------------------------------------
class ParkArea(str, Enum):
    FRONTIER = "FRONTIER"
    LAGOON = "LAGOON"
    SKYLINE = "SKYLINE"
    KIDS_COVE = "KIDS_COVE"


class RideClass(str, Enum):
    KIDDIE = "KIDDIE"
    FAMILY = "FAMILY"
    THRILL = "THRILL"
    WATER = "WATER"


class OperationalPosture(str, Enum):
    OPEN = "OPEN"
    CLOSED_PENDING_INSPECTION = "CLOSED_PENDING_INSPECTION"
    DOWN = "DOWN"
    HOLD = "HOLD"
    OVERHAUL = "OVERHAUL"


class ComponentType(str, Enum):
    BRAKE = "BRAKE"
    LIFT_CHAIN = "LIFT_CHAIN"
    RESTRAINT_ACTUATOR = "RESTRAINT_ACTUATOR"
    GEARBOX = "GEARBOX"
    AXLE = "AXLE"
    CONTROL_PLC = "CONTROL_PLC"


class Criticality(str, Enum):
    SAFETY_CRITICAL = "SAFETY_CRITICAL"
    ESSENTIAL = "ESSENTIAL"
    NON_CRITICAL = "NON_CRITICAL"


class NdtStatus(str, Enum):
    CURRENT = "CURRENT"
    DUE = "DUE"
    OVERDUE = "OVERDUE"


class ConditionFlag(str, Enum):
    OK = "OK"
    SUSPECT = "SUSPECT"
    FAILED = "FAILED"


class NdtMethod(str, Enum):
    MAGNETIC_PARTICLE = "MAGNETIC_PARTICLE"
    ULTRASONIC = "ULTRASONIC"
    DYE_PENETRANT = "DYE_PENETRANT"
    EDDY_CURRENT = "EDDY_CURRENT"
    VISUAL = "VISUAL"


class NdtResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class TemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class SeverityClass(str, Enum):
    SAFETY_CRITICAL = "SAFETY_CRITICAL"
    ESSENTIAL = "ESSENTIAL"
    ADVISORY = "ADVISORY"


class InspectionStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    PENDING_SIGN_OFF = "PENDING_SIGN_OFF"
    REJECTED = "REJECTED"
    SIGNED_OFF = "SIGNED_OFF"


class ItemOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    NA = "NA"


class BulletinSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    MANDATORY = "MANDATORY"
    RECALL = "RECALL"


class BulletinStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class BulletinActionStatus(str, Enum):
    PENDING = "PENDING"
    IN_WORK = "IN_WORK"
    VERIFIED = "VERIFIED"
    DEFERRED = "DEFERRED"
    CANCELLED = "CANCELLED"


class CauseCategory(str, Enum):
    MECHANICAL = "MECHANICAL"
    ELECTRICAL = "ELECTRICAL"
    GUEST_ILLNESS = "GUEST_ILLNESS"
    WEATHER = "WEATHER"
    INSPECTION_FAIL = "INSPECTION_FAIL"
    OPERATOR = "OPERATOR"


class DowntimeStatus(str, Enum):
    OPEN = "OPEN"
    DIAGNOSED = "DIAGNOSED"
    AWAITING_PARTS = "AWAITING_PARTS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class RequisitionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RESERVED = "RESERVED"
    BACKORDERED = "BACKORDERED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class CertificationStatus(str, Enum):
    TRAINEE = "TRAINEE"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class InjurySeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    FATAL = "FATAL"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    RIDE_HELD = "RIDE_HELD"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    REGULATOR_NOTIFIED = "REGULATOR_NOTIFIED"
    INTERNAL_REVIEW_CLOSED = "INTERNAL_REVIEW_CLOSED"
    CLEARED_TO_OPERATE = "CLEARED_TO_OPERATE"


class WorkOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    TEARDOWN = "TEARDOWN"
    INSPECTION = "INSPECTION"
    REBUILD = "REBUILD"
    RECOMMISSIONED = "RECOMMISSIONED"


# --- Entities ---------------------------------------------------------------
class Attraction(TypedDict):
    id: str
    name: str
    park_area: str
    manufacturer: str
    model_code: str
    ride_class: str
    theoretical_hourly_capacity: int
    min_operators_required: int
    parts_budget_cents: int
    mean_repair_minutes: int
    operational_posture: str
    cumulative_cycles: int
    parts_budget_committed_cents: int
    ytd_downtime_minutes: int
    certified_operator_count: int
    regulatory_hold: bool
    active_template_id: Optional[str]
    last_signed_off_service_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComponentAsset(TypedDict):
    id: str
    attraction_id: str
    name: str
    component_type: str
    criticality: str
    ndt_interval_cycles: int
    ndt_interval_days: int
    last_ndt_at: Optional[str]
    last_ndt_cycles: int
    last_ndt_method: Optional[str]
    cycles_since_last_ndt: int
    ndt_status: str
    condition_flag: str
    created_at: str
    updated_at: str
    version: int


class InspectionTemplate(TypedDict):
    id: str
    attraction_id: str
    revision: int
    effective_from_date: str
    status: str
    item_count: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# PRD §2.5: a checklist line "carries only `id` and `created_at`. It has no
# `updated_at`, no `version`, and no update endpoint."
class ChecklistItem(TypedDict):
    id: str
    template_id: str
    sequence_no: int
    description: str
    severity_class: str
    component_id: Optional[str]
    requires_photo: bool
    created_at: str


class DailyInspection(TypedDict):
    id: str
    attraction_id: str
    service_date: str
    template_id: str
    template_revision: int
    status: str
    pending_item_count: int
    blocking_item_count: int
    essential_fail_count: int
    opened_by_user_id: str
    recorded_by_user_ids: List[str]
    signed_off_by_user_id: Optional[str]
    signed_off_at: Optional[str]
    rejection_reason: Optional[str]
    rework_round: int
    created_at: str
    updated_at: str
    version: int


class InspectionItemResult(TypedDict):
    id: str
    inspection_id: str
    checklist_item_id: str
    severity_class: str
    outcome: str
    note: Optional[str]
    requires_photo: bool
    recorded_by_user_id: Optional[str]
    recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceBulletin(TypedDict):
    id: str
    bulletin_ref: str
    manufacturer: str
    model_code: str
    severity: str
    issued_date: str
    compliance_deadline_date: str
    supersedes_bulletin_id: Optional[str]
    status: str
    action_total_count: int
    action_verified_count: int
    acknowledged_at: Optional[str]
    acknowledged_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BulletinAction(TypedDict):
    id: str
    bulletin_id: str
    attraction_id: str
    status: str
    required_part_received: bool
    deferral_reason: Optional[str]
    deferred_until_date: Optional[str]
    deferral_count: int
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DowntimeEvent(TypedDict):
    id: str
    attraction_id: str
    service_date: str
    started_at: str
    ended_at: Optional[str]
    cause_category: str
    root_cause_code: Optional[str]
    failed_component_id: Optional[str]
    status: str
    auto_opened: bool
    duration_minutes: Optional[int]
    peak_minutes: Optional[int]
    off_peak_minutes: Optional[int]
    settled_guest_slots_lost: Optional[float]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartRequisition(TypedDict):
    id: str
    attraction_id: str
    part_number: str
    quantity: int
    unit_cost_cents: int
    total_cost_cents: int
    needed_by_date: str
    downtime_event_id: Optional[str]
    bulletin_action_id: Optional[str]
    status: str
    expected_availability_date: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OperatorCertification(TypedDict):
    id: str
    attraction_id: str
    operator_user_id: str
    effective_from: str
    expires_at: str
    restraint_verification_score: int
    dispatch_procedure_score: int
    status: str
    suspended_at: Optional[str]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    attraction_id: str
    occurred_at: str
    injury_severity: str
    guest_count_affected: int
    narrative: str
    status: str
    regulator_notification_due_at: Optional[str]
    regulator_case_ref: Optional[str]
    notified_at: Optional[str]
    notified_late: bool
    investigator_user_id: Optional[str]
    regulator_clearance_ref: Optional[str]
    cleared_at: Optional[str]
    suspended_certification_count: int
    created_at: str
    updated_at: str
    version: int


class ShopBay(TypedDict):
    id: str
    name: str
    concurrent_slot_capacity: int
    booked_order_count: int
    created_at: str
    updated_at: str
    version: int


class OverhaulWorkOrder(TypedDict):
    id: str
    attraction_id: str
    component_id: str
    shop_bay_id: str
    window_start_date: str
    window_end_date: str
    parts_subtotal_cents: int
    labor_hours: float
    expedite_requested: bool
    off_season: bool
    base_total_cents: int
    off_season_discount_cents: int
    discounted_base_cents: int
    expedite_pct: float
    expedite_fee_cents: int
    estimated_total_cents: int
    status: str
    recommissioned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Computed read payloads -------------------------------------------------
class CapacityImpact(TypedDict):
    attraction_id: str
    window_start_date: str
    window_end_date: str
    event_count: int
    settled_guest_slots_lost: float
    provisional_guest_slots_lost: float
    divergence_guest_slots: float


class DispatchReadiness(TypedDict):
    attraction_id: str
    operational_posture: str
    certified_operator_count: int
    mean_restraint_score: float
    essential_fail_count: int
    dispatch_readiness_index: float


class BulletinRisk(TypedDict):
    bulletin_id: str
    evaluated_action_count: int
    deferred_action_count: int
    escalation_factor: float
    fleet_aggregate_score: float
    per_unit_max_score: float
    divergence: float
