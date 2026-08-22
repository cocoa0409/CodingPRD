"""Domain types for the Airline Station Ground Handling API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    STATION_MANAGER = "StationManager"
    DUTY_OFFICER = "DutyOfficer"
    SAFETY_OFFICER = "SafetyOfficer"
    BILLING_CONTROLLER = "BillingController"
    CONTRACT_AUDITOR = "ContractAuditor"
    SUBCONTRACTOR_ADMIN = "SubcontractorAdmin"


# ─── Station ──────────────────────────────────────────────────────────────

class StationStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SeasonCode(str, Enum):
    SUMMER = "SUMMER"
    WINTER = "WINTER"


class OversightPosture(str, Enum):
    NORMAL = "NORMAL"
    ENHANCED = "ENHANCED"
    RESTRICTED = "RESTRICTED"


class StationAction(str, Enum):
    OPEN = "OPEN"
    SUSPEND = "SUSPEND"
    RESUME = "RESUME"
    CLOSE = "CLOSE"


# ─── Subcontractor ────────────────────────────────────────────────────────

class SubcontractorStatus(str, Enum):
    PENDING_VETTING = "PENDING_VETTING"
    APPROVED = "APPROVED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SubcontractorTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class OversightDecision(str, Enum):
    APPROVE = "APPROVE"
    PLACE_ON_PROBATION = "PLACE_ON_PROBATION"
    REINSTATE = "REINSTATE"
    SUSPEND = "SUSPEND"
    TERMINATE = "TERMINATE"


# ─── FlightBank ───────────────────────────────────────────────────────────

class BankStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    ARCHIVED = "ARCHIVED"


class StaffingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUIRED = "REVISION_REQUIRED"


class BankAction(str, Enum):
    PUBLISH = "PUBLISH"
    LOCK = "LOCK"
    ARCHIVE = "ARCHIVE"


class StaffingAction(str, Enum):
    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REVISE = "REVISE"


# ─── Turn ─────────────────────────────────────────────────────────────────

class TurnType(str, Enum):
    TOWING_ONLY = "TOWING_ONLY"
    NARROWBODY_QUICK = "NARROWBODY_QUICK"
    NARROWBODY_STANDARD = "NARROWBODY_STANDARD"
    FREIGHTER = "FREIGHTER"
    WIDEBODY = "WIDEBODY"


class TurnStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESOURCED = "RESOURCED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DISRUPTED = "DISRUPTED"


class OtpResult(str, Enum):
    PENDING = "PENDING"
    ON_TIME = "ON_TIME"
    DELAYED = "DELAYED"
    EXCLUDED = "EXCLUDED"


class DelayCode(str, Enum):
    GH_STAFFING = "GH_STAFFING"
    GH_EQUIPMENT = "GH_EQUIPMENT"
    GH_LOADING = "GH_LOADING"
    CARRIER = "CARRIER"
    ATC = "ATC"
    WEATHER = "WEATHER"
    NONE = "NONE"


class TurnAction(str, Enum):
    START = "START"
    COMPLETE = "COMPLETE"
    CANCEL = "CANCEL"


# ─── Agent / Certification ────────────────────────────────────────────────

class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EmploymentType(str, Enum):
    DIRECT = "DIRECT"
    SUBCONTRACTED = "SUBCONTRACTED"


class CertificationPosture(str, Enum):
    CURRENT = "CURRENT"
    EXPIRING = "EXPIRING"
    LAPSED = "LAPSED"


class CertType(str, Enum):
    RAMP_SAFETY = "RAMP_SAFETY"
    PUSHBACK = "PUSHBACK"
    BELT_LOADER = "BELT_LOADER"
    GPU = "GPU"
    DEICING = "DEICING"
    LOADMASTER = "LOADMASTER"


class CertificationStatus(str, Enum):
    VALID = "VALID"
    REVOKED = "REVOKED"


class CurrencyState(str, Enum):
    CURRENT = "CURRENT"
    EXPIRING = "EXPIRING"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


# ─── GSE ──────────────────────────────────────────────────────────────────

class GseType(str, Enum):
    PUSHBACK_TUG = "PUSHBACK_TUG"
    BELT_LOADER = "BELT_LOADER"
    GPU = "GPU"
    DEICER = "DEICER"
    STAIRS = "STAIRS"


class GseStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


class ServiceEventType(str, Enum):
    HOLD_SCHEDULED = "HOLD_SCHEDULED"
    SERVICE_COMPLETED = "SERVICE_COMPLETED"


# ─── TurnResource ─────────────────────────────────────────────────────────

class ResourceKind(str, Enum):
    AGENT = "AGENT"
    GSE = "GSE"


class RoleOnTurn(str, Enum):
    LEAD = "LEAD"
    RAMP = "RAMP"
    LOADER = "LOADER"
    PUSHBACK_OPERATOR = "PUSHBACK_OPERATOR"
    DEICER = "DEICER"


class TurnResourceStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    GSE_QUARANTINED = "GSE_QUARANTINED"
    AGENT_SUSPENDED = "AGENT_SUSPENDED"
    SUBCONTRACTOR_TERMINATED = "SUBCONTRACTOR_TERMINATED"
    STATION_SUSPENDED = "STATION_SUSPENDED"
    SEASON_ROLLOVER = "SEASON_ROLLOVER"


# ─── Incident ─────────────────────────────────────────────────────────────

class IncidentType(str, Enum):
    AIRCRAFT_DAMAGE = "AIRCRAFT_DAMAGE"
    GSE_DAMAGE = "GSE_DAMAGE"
    PERSONAL_INJURY = "PERSONAL_INJURY"
    NEAR_MISS = "NEAR_MISS"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class LiabilityParty(str, Enum):
    HANDLER = "HANDLER"
    SUBCONTRACTOR = "SUBCONTRACTOR"
    CARRIER = "CARRIER"
    THIRD_PARTY = "THIRD_PARTY"


class IncidentAction(str, Enum):
    INVESTIGATE = "INVESTIGATE"
    ISSUE_FINDINGS = "ISSUE_FINDINGS"
    CLOSE = "CLOSE"
    REOPEN = "REOPEN"


# ─── Billing ──────────────────────────────────────────────────────────────

class BillingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"


class BillingPeriodAction(str, Enum):
    FINALIZE = "FINALIZE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class RebateTier(str, Enum):
    NONE = "NONE"
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"


class BillingLineStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    VOID = "VOID"


class GroundTimeTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


# ─── Entity shapes ────────────────────────────────────────────────────────
# Every record type carries id, created_at, updated_at and version.

class Station(TypedDict):
    id: str
    iata_code: str
    name: str
    handler_code: str
    status: str
    season_code: str
    season_start_date: Optional[str]
    season_end_date: Optional[str]
    otp_target_pct: float
    otp_tolerance_minutes: int
    gse_reposition_buffer_minutes: int
    penalty_cap_cents: int
    damage_penalty_multiplier: float
    oversight_posture: str
    open_critical_incident_count: int
    open_major_incident_count: int
    completed_turn_count: int
    on_time_turn_count: int
    otp_rolling_pct: float
    opened_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subcontractor(TypedDict):
    id: str
    station_id: str
    parent_subcontractor_id: Optional[str]
    legal_name: str
    tier: str
    status: str
    closed_liable_incident_count: int
    total_incident_count: int
    compliance_score: float
    audit_compliance_score: float
    oversight_flag: bool
    created_at: str
    updated_at: str
    version: int


class FlightBank(TypedDict):
    id: str
    station_id: str
    bank_code: str
    season_code: str
    window_start: str
    window_end: str
    bank_status: str
    staffing_status: str
    planned_headcount: int
    required_headcount: int
    turn_count: int
    staffing_coverage_pct: float
    last_staffing_decision_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Turn(TypedDict):
    id: str
    station_id: str
    flight_bank_id: str
    flight_number: str
    turn_type: str
    scheduled_in: str
    scheduled_out: str
    actual_in: Optional[str]
    actual_out: Optional[str]
    scheduled_ground_minutes: int
    actual_ground_minutes: Optional[int]
    delay_minutes: Optional[int]
    delay_code: Optional[str]
    otp_result: str
    status: str
    required_agent_count: int
    required_gse_count: int
    assigned_agent_count: int
    assigned_gse_count: int
    billed: bool
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict):
    id: str
    station_id: str
    subcontractor_id: Optional[str]
    employee_code: str
    full_name: str
    employment_type: str
    status: str
    certification_posture: str
    assigned_duty_minutes: int
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    agent_id: str
    station_id: str
    cert_type: str
    issued_at: str
    expires_at: str
    status: str
    currency_state: str
    revoked_at: Optional[str]
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GseUnit(TypedDict):
    id: str
    station_id: str
    asset_tag: str
    gse_type: str
    status: str
    condition_score: int
    service_interval_cycles: int
    cycles_since_service: int
    service_hold_start: Optional[str]
    service_hold_end: Optional[str]
    committed_occupation_minutes: int
    last_service_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TurnResource(TypedDict):
    id: str
    turn_id: str
    agent_id: Optional[str]
    gse_unit_id: Optional[str]
    resource_kind: str
    role_on_turn: Optional[str]
    gse_type: Optional[str]
    window_start: str
    window_end: str
    occupied_minutes: int
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    station_id: str
    turn_id: Optional[str]
    gse_unit_id: Optional[str]
    agent_id: Optional[str]
    subcontractor_id: Optional[str]
    incident_type: str
    severity: str
    occurred_at: str
    description: Optional[str]
    status: str
    reported_by_user_id: str
    investigator_user_id: Optional[str]
    findings_issued_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    root_cause_code: Optional[str]
    liability_party: Optional[str]
    assessed_damage_cents: Optional[int]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict):
    id: str
    station_id: str
    period_code: str
    window_start: str
    window_end: str
    status: str
    line_count: int
    accrued_cents: int
    gross_total_cents: int
    otp_penalty_cents: int
    damage_penalty_cents: int
    rebate_tier: str
    rebate_cents: int
    net_total_cents: int
    finalized_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    reject_count: int
    created_at: str
    updated_at: str
    version: int


class BillingLine(TypedDict):
    id: str
    billing_period_id: str
    turn_id: str
    turn_type_snapshot: str
    status: str
    base_rate_cents: int
    charged_ground_minutes: int
    excess_minutes: int
    ground_time_tier: str
    gross_amount_cents: int
    otp_penalty_cents: int
    damage_penalty_cents: int
    rebate_alloc_cents: int
    net_amount_cents: int
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
