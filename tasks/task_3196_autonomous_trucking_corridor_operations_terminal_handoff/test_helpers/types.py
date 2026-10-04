"""Domain types for the Autonomous Trucking Corridor Operations API.

Entity TypedDicts, status enums and the role enum, derived from the PRD's
entity and state-machine definitions. Every entity declared for this domain is
mutable and therefore carries the full common-field set (``id``, ``created_at``,
``updated_at``, ``version``).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum types ────────────────────────────────────────────────────

class CorridorStatus(str, Enum):
    PLANNED = "PLANNED"
    READINESS_REVIEW = "READINESS_REVIEW"
    ACTIVE = "ACTIVE"
    LIMITED = "LIMITED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class CorridorPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class WeatherProfile(str, Enum):
    CLEAR_DEFAULT = "CLEAR_DEFAULT"
    HIGH_WIND = "HIGH_WIND"
    HEAVY_PRECIPITATION = "HEAVY_PRECIPITATION"
    LOW_VISIBILITY = "LOW_VISIBILITY"
    WINTER_SURFACE = "WINTER_SURFACE"


class TerminalState(str, Enum):
    COMMISSIONING = "COMMISSIONING"
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    CLOSED = "CLOSED"


class StaffingStatus(str, Enum):
    STAFFED = "STAFFED"
    UNDERSTAFFED = "UNDERSTAFFED"


class CheckType(str, Enum):
    SENSOR_CALIBRATION = "SENSOR_CALIBRATION"
    ROUTE_VALIDATION = "ROUTE_VALIDATION"
    LOAD_SECUREMENT = "LOAD_SECUREMENT"


class CheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


class CheckStatus(str, Enum):
    INITIALIZED = "INITIALIZED"
    CALIBRATION_PASSED = "CALIBRATION_PASSED"
    VALIDATED = "VALIDATED"
    EXPIRED_FAILED = "EXPIRED_FAILED"


class RunStatus(str, Enum):
    DRAFT = "DRAFT"
    READINESS_PENDING = "READINESS_PENDING"
    DISPATCH_READY = "DISPATCH_READY"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class SafetyBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SafetyTier(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class IncidentBand(str, Enum):
    CLEAN = "CLEAN"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


class CarrierStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class CommitmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    REVOKED = "REVOKED"


class WindowStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    DISPLACED = "DISPLACED"
    CANCELLED = "CANCELLED"


class ServiceType(str, Enum):
    HANDOFF_INBOUND = "HANDOFF_INBOUND"
    HANDOFF_OUTBOUND = "HANDOFF_OUTBOUND"
    YARD_TRANSFER = "YARD_TRANSFER"
    MAINTENANCE_STAGING = "MAINTENANCE_STAGING"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MONITORING = "MONITORING"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    CRITICAL = "CRITICAL"


class IncidentTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class IncidentStatus(str, Enum):
    FILED = "FILED"
    INVESTIGATING = "INVESTIGATING"
    CORRECTIVE_ACTION = "CORRECTIVE_ACTION"
    SUBMITTED = "SUBMITTED"
    CLOSED = "CLOSED"


class Pathway(str, Enum):
    FIRST_LAST_MILE = "FIRST_LAST_MILE"
    REMOTE_SUPPORT = "REMOTE_SUPPORT"
    FLEET_TECHNICIAN = "FLEET_TECHNICIAN"
    TRANSFER_HUB = "TRANSFER_HUB"
    RIDE_ALONG_EVALUATOR = "RIDE_ALONG_EVALUATOR"


class TransitionStatus(str, Enum):
    ENROLLED = "ENROLLED"
    RIDE_ALONG_VERIFIED = "RIDE_ALONG_VERIFIED"
    CREDENTIAL_LAPSED = "CREDENTIAL_LAPSED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class SafetyCaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FILED = "FILED"


class SafetyCaseSummary(str, Enum):
    NOT_FILED = "NOT_FILED"
    CURRENT = "CURRENT"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    INSPECTED = "INSPECTED"
    VOIDED = "VOIDED"
    CLOSED = "CLOSED"


class ProgramsStatus(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    OVERDUE = "OVERDUE"
    UNFILLED = "UNFILLED"


class EngagementType(str, Enum):
    SAFETY_BRIEFING = "SAFETY_BRIEFING"
    OPERATIONAL_NOTICE = "OPERATIONAL_NOTICE"
    INCIDENT_DISCLOSURE = "INCIDENT_DISCLOSURE"
    HOURS_ALLOCATION_REQUEST = "HOURS_ALLOCATION_REQUEST"


class EngagementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ConventionStatus(str, Enum):
    NORMAL = "NORMAL"
    SENSITIVE = "SENSITIVE"
    HIGH_CONSEQUENCE = "HIGH_CONSEQUENCE"


class SecurityClassification(str, Enum):
    NORMAL = "NORMAL"
    SENSITIVE = "SENSITIVE"
    HIGH_CONSEQUENCE = "HIGH_CONSEQUENCE"


class ClauseStatus(str, Enum):
    PENDING = "PENDING"
    ELECTED = "ELECTED"
    DECLINED = "DECLINED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXECUTED = "EXECUTED"


class GeofenceType(str, Enum):
    GEOFENCE_ONLY = "GEOFENCE_ONLY"
    GEOFENCE_PLUS_BUFFER = "GEOFENCE_PLUS_BUFFER"


class InterventionProtocol(str, Enum):
    MONITOR_ONLY = "MONITOR_ONLY"
    VOICE_ADVISORY = "VOICE_ADVISORY"
    STANDBY_TAKEOVER = "STANDBY_TAKEOVER"
    REMOTE_DISENGAGE = "REMOTE_DISENGAGE"


class UnitStatus(str, Enum):
    PENDING = "PENDING"
    INGATED = "INGATED"
    LOADED = "LOADED"
    ON_VESSEL = "ON_VESSEL"
    DISCHARGED = "DISCHARGED"
    OFFLOADED = "OFFLOADED"
    GATED_OUT = "GATED_OUT"


class UserRole(str, Enum):
    ANY = "Any"
    PLATFORM_ADMIN = "PlatformAdmin"
    CORRIDOR_OPERATIONS_MANAGER = "CorridorOperationsManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CARRIER_DISPATCHER = "CarrierDispatcher"
    TERMINAL_MANAGER = "TerminalManager"
    REMOTE_SUPPORT_SUPERVISOR = "RemoteSupportSupervisor"
    REMOTE_SUPPORT_OPERATOR = "RemoteSupportOperator"
    INCIDENT_REVIEWER = "IncidentReviewer"
    SAFETY_CASE_AUTHOR = "SafetyCaseAuthor"
    REGULATORY_LIAISON = "RegulatoryLiaison"
    FLEET_MAINTENANCE_TECH = "FleetMaintenanceTech"
    DRIVER_OUTREACH_COORDINATOR = "DriverOutreachCoordinator"
    SHIPPER_PARTNERSHIP_MANAGER = "ShipperPartnershipManager"
    BOOKING_CLERK = "BookingClerk"
    TERMINAL_OPERATOR = "TerminalOperator"
    EXCHANGE_PARTICIPANT = "ExchangeParticipant"


# ─── Entity TypedDicts (common_fields: true) ────────────────────────────────

class Terminal(TypedDict, total=False):
    id: str
    terminal_code: str
    terminal_name: str
    state_code: str
    apron_capacity: int
    reserved_apron_units: float
    terminal_state: str
    staffing_status: Optional[str]
    transfer_turnaround_minutes: float
    total_handoff_minutes: int
    approved_window_count: int
    created_at: str
    updated_at: str
    version: int


class Corridor(TypedDict, total=False):
    id: str
    corridor_name: str
    origin_terminal_id: str
    destination_terminal_id: str
    highway_segment_miles: float
    mapped_route: dict
    weather_profile: str
    weather_risk_score: int
    corridor_status: str
    posture: str
    check_pass_count: int
    check_count: int
    has_blocking_incident: bool
    route_validation_calculated_at: Optional[str]
    launch_authorized_at: Optional[str]
    readiness_score: float
    created_at: str
    updated_at: str
    version: int


class LaunchReadinessCheck(TypedDict, total=False):
    id: str
    corridor_id: str
    check_type: str
    check_result: str
    suite_latitude: float
    suite_longitude: float
    calibration_variance_ms: float
    load_payload_lbs: int
    prior_run_plan_id: Optional[str]
    valid_window_days: int
    valid_window_start_at: str
    check_status: str
    check_contribution: float
    is_test_payload: bool
    correlation_key: Optional[str]
    epoch_start_at: str
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict, total=False):
    id: str
    carrier_name: str
    dot_number: str
    safety_score: int
    rate_settlement_cents: float
    safety_tier: str
    committed_discount_cents: float
    recordable_incidents_last_epoch: int
    previous_epoch_incidents: int
    incident_band: str
    backup_carrier_id: Optional[str]
    backup_carrier_score: int
    carrier_status: str
    created_at: str
    updated_at: str
    version: int


class ShipperCommitment(TypedDict, total=False):
    id: str
    shipper_name: str
    shipper_floor_per_mile_cents: float
    reserved_window_start_epoch_day: int
    reserved_window_end_epoch_day: int
    committed_slots: int
    ride_along_credit_cents: float
    billed_ride_along_cents: float
    consumed_slots: int
    remaining_slots: int
    verified_ride_along_count: int
    commitment_status: str
    shipped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RunPlan(TypedDict, total=False):
    id: str
    corridor_id: str
    carrier_id: str
    origin_terminal_id: str
    destination_terminal_id: str
    shipper_commitment_id: str
    window_start_epoch_day: int
    window_end_epoch_day: int
    trailer_count: int
    hauler_team_id: str
    sacra_loadboard_slot_held: bool
    run_status: str
    posted_per_mile_cents: float
    per_mile_rate_cents: float
    committed_rate_cents: float
    scenario_rate_cents: float
    run_window_rate_cents: float
    safety_score: int
    safety_band: str
    created_at: str
    updated_at: str
    version: int


class TerminalServiceWindow(TypedDict, total=False):
    id: str
    terminal_id: str
    run_plan_id: str
    service_type: str
    window_start_minute: int
    window_end_minute: int
    handoff_duration_minutes: int
    buffer_minutes: int
    yield_to_transit: bool
    window_status: str
    buffer_seconds: int
    created_at: str
    updated_at: str
    version: int


class RemoteSupportAssignment(TypedDict, total=False):
    id: str
    corridor_id: str
    run_plan_id: str
    monitoring_start_at: str
    monitoring_end_at: str
    remote_operator_id: str
    safety_support_operator_id: str
    geofence_type: str
    intervention_protocol: str
    intervention_count: int
    safe_stop_required: bool
    safe_stop_fee_cents: float
    assignment_status: str
    closure_source: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict, total=False):
    id: str
    corridor_id: str
    run_plan_id: str
    severity: str
    recordable_incidents: int
    corrective_action_count: int
    incident_tier: str
    review_days_allowed: int
    report_status: str
    regulatory_notice_required: bool
    report_sequence_number: int
    created_at: str
    updated_at: str
    version: int


class DriverProspect(TypedDict, total=False):
    id: str
    prospect_name: str
    home_terminal_id: str
    pathway: str
    hours_worked: int
    enrollments_on_file: int
    safety_reliability_score: float
    created_at: str
    updated_at: str
    version: int


class DriverTransition(TypedDict, total=False):
    id: str
    prospect_id: str
    terminal_id: str
    pathway: str
    transition_start_epoch_day: int
    transition_days_count: int
    transition_end_epoch_day: int
    hours_recorded: int
    credential_event_count: int
    transition_status: str
    created_at: str
    updated_at: str
    version: int


class SafetyCase(TypedDict, total=False):
    id: str
    corridor_id: str
    safety_case_version: int
    case_status: str
    filed_date: Optional[str]
    hazard_count: int
    open_hazard_count: int
    residual_risk_score: float
    case_status_summary: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceProgram(TypedDict, total=False):
    id: str
    program_name: str
    fleet_unit_id: str
    state_code: str
    inspection_interval_days: int
    inspection_odometer_miles: int
    standard_inspection_due_date: str
    inspection_programs_status: str
    program_status: str
    last_inspection_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FleetUnit(TypedDict, total=False):
    id: str
    unit_id: str
    fleet_name: str
    home_terminal_id: str
    curated_at: str
    inspection_anchor_at: str
    weather_clearance_hours: int
    is_watch_squad: bool
    hours_posted_total: int
    route_driven_hours_cents: float
    maint_projection_cents: float
    maint_charges: int
    remain_hours: int
    unit_status: str
    created_at: str
    updated_at: str
    version: int


class StateAuthority(TypedDict, total=False):
    id: str
    state_code: str
    authority_name: str
    autonomous_hours_allowed: int
    requires_safety_case_filed: bool
    engagement_window_days: int
    hours_used: int
    remaining_autonomous_hours: int
    filing_required_next: bool
    created_at: str
    updated_at: str
    version: int


class RegulatoryEngagement(TypedDict, total=False):
    id: str
    corridor_id: str
    state_authority_id: str
    engagement_type: str
    autonomous_hours_requested: int
    autonomous_hours_logged: int
    engaged_at: str
    engagement_status: str
    state_status: str
    hours_charge_allowed: bool
    created_at: str
    updated_at: str
    version: int


class LedgerCheckpoint(TypedDict, total=False):
    id: str
    checkpoint_code: str
    epoch_start_at: str
    epoch_end_at: str
    hours_per_epoch: int
    adopted_at: Optional[str]
    checkpoint_status: str
    rolled_over_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RunPlanHauler(TypedDict, total=False):
    id: str
    run_plan_id: str
    driver_transition_id: str
    hauler_role: str
    hauler_status: str
    created_at: str
    updated_at: str
    version: int


class SecurityRecord(TypedDict, total=False):
    id: str
    security_code: str
    origin_terminal_id: str
    destination_terminal_id: Optional[str]
    security_classification: str
    clearance_required: bool
    high_consequence_clearance: bool
    convention_status: str
    consignor_code: str
    outbound_lane_code: Optional[str]
    record_status: str
    created_at: str
    updated_at: str
    version: int


class ClauseVariant(TypedDict, total=False):
    id: str
    clause_stem: str
    wildcard: bool
    variant_code: str
    variant_status: str
    variant_status_summary: str
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgreementCode(TypedDict, total=False):
    id: str
    code_value: str
    display_value: str
    code_status: str
    exec_sequence: int
    order_sentinel: str
    created_at: str
    updated_at: str
    version: int


class MultiDayHold(TypedDict, total=False):
    id: str
    coverage_date: Optional[str]
    hold_start_epoch_day: int
    hold_end_epoch_day: int
    single_day_hold: bool
    sequence_in_chain: int
    hold_type: str
    hold_status: str
    created_at: str
    updated_at: str
    version: int


class RunPlanChassis(TypedDict, total=False):
    id: str
    run_plan_id: str
    chassis_code: str
    coverage_days: int
    holding_rate_cents: float
    chassis_status: str
    created_at: str
    updated_at: str
    version: int


class ShippingInstruction(TypedDict, total=False):
    id: str
    run_plan_id: str
    container_unit_ids: List[str]
    booked_vgm_kg_sum: float
    booked_line_total_cents: float
    vgm_override_fee_cents: float
    container_discount_cents: float
    instruction_status: str
    created_at: str
    updated_at: str
    version: int


class ContainerUnit(TypedDict, total=False):
    id: str
    instruction_id: Optional[str]
    container_number: str
    length_feet: int
    gross_weight_kg: float
    verified_gross_mass_kg: float
    unit_rate_cents: float
    unit_status: str
    created_at: str
    updated_at: str
    version: int