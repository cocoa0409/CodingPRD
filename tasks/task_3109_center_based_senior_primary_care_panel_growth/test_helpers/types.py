"""Domain types: entity TypedDicts, status enums, and the role enum.

Every entity carries the common four-field set (id, created_at, updated_at,
version); no entity in this domain omits updated_at or version.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    NETWORK_OPERATOR = "NetworkOperator"
    ENROLLMENT_COORDINATOR = "EnrollmentCoordinator"
    CARE_TEAM_LEAD = "CareTeamLead"
    FRONT_DESK = "FrontDesk"
    TRANSPORT_DISPATCHER = "TransportDispatcher"
    TRIAGE_NURSE = "TriageNurse"
    CLAIMS_ADJUDICATOR = "ClaimsAdjudicator"
    FINANCE_ANALYST = "FinanceAnalyst"
    FINANCE_CONTROLLER = "FinanceController"


class CenterStatus(str, Enum):
    PRE_OPEN = "PRE_OPEN"
    OPEN = "OPEN"
    SATURATED = "SATURATED"
    CLOSED = "CLOSED"


class ProfitabilityTier(str, Enum):
    RAMP = "RAMP"
    BREAKEVEN = "BREAKEVEN"
    MATURE = "MATURE"


class AttributionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    WAITLISTED = "WAITLISTED"
    DISENROLLED = "DISENROLLED"
    REATTRIBUTED = "REATTRIBUTED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    COMPLETED_NO_SHOW = "COMPLETED_NO_SHOW"
    CANCELLED = "CANCELLED"


class AppointmentKind(str, Enum):
    PRIMARY = "PRIMARY"
    BEHAVIORAL = "BEHAVIORAL"
    CHW_OUTREACH = "CHW_OUTREACH"


class RideStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    EN_ROUTE = "EN_ROUTE"
    DELIVERED = "DELIVERED"
    FAILED_NO_SHOW = "FAILED_NO_SHOW"
    RECOVERED = "RECOVERED"
    CANCELLED = "CANCELLED"


class TriageStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_DIVERTED = "RESOLVED_DIVERTED"
    RESOLVED_ED = "RESOLVED_ED"
    RESOLVED_SELF_CARE = "RESOLVED_SELF_CARE"
    EXPIRED = "EXPIRED"


class TriageChannel(str, Enum):
    AFTER_HOURS_LINE = "AFTER_HOURS_LINE"
    WALK_IN = "WALK_IN"
    CARE_TEAM_ESCALATION = "CARE_TEAM_ESCALATION"


class TriageSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class TriageDisposition(str, Enum):
    URGENT_CARE_BOOKED = "URGENT_CARE_BOOKED"
    ED_REFERRED = "ED_REFERRED"
    SELF_CARE_ADVISED = "SELF_CARE_ADVISED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class ClaimCategory(str, Enum):
    ED_VISIT = "ED_VISIT"
    INPATIENT = "INPATIENT"
    SPECIALIST = "SPECIALIST"
    PHARMACY = "PHARMACY"
    TRANSPORT = "TRANSPORT"
    INTERNAL_VISIT = "INTERNAL_VISIT"


class SettlementStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_PROVISIONAL = "CLOSED_PROVISIONAL"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class ContractType(str, Enum):
    FULL_RISK = "FULL_RISK"
    SHARED_SAVINGS = "SHARED_SAVINGS"


class Center(TypedDict, total=False):
    id: str
    name: str
    neighborhood_code: str
    opened_on: str
    maturity_months: int
    profitability_tier: str
    panel_fill_ratio: float
    cumulative_contribution_cents: int
    ed_referral_count_current_month: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CareTeam(TypedDict, total=False):
    id: str
    center_id: str
    team_label: str
    panel_cap: int
    physician_count: int
    chw_count: int
    behavioral_count: int
    staffing_score: float
    active_panel_count: int
    waitlist_depth: int
    accepting: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    zip_code: str
    risk_score: float
    transport_dependent: bool
    no_show_strikes: int
    created_at: str
    updated_at: str
    version: int


class HealthPlan(TypedDict, total=False):
    id: str
    plan_name: str
    contract_type: str
    base_pmpm_cents: int
    risk_adjust_factor: float
    revenue_share_pct: float
    created_at: str
    updated_at: str
    version: int


class PatientAttribution(TypedDict, total=False):
    id: str
    patient_id: str
    health_plan_id: str
    care_team_id: str
    effective_month: str
    status: str
    disenrolled_month: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    care_team_id: str
    patient_id: str
    room_id: str
    start_utc: str
    duration_minutes: int
    kind: str
    status: str
    cost_cents: int
    created_at: str
    updated_at: str
    version: int


class CenterRoom(TypedDict, total=False):
    id: str
    center_id: str
    room_label: str
    supports_behavioral: bool
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    center_id: str
    plate: str
    seat_capacity: int
    wheelchair_capable: bool
    created_at: str
    updated_at: str
    version: int


class RideRequest(TypedDict, total=False):
    id: str
    appointment_id: str
    patient_id: str
    pickup_window_start: str
    pickup_window_end: str
    assigned_vehicle_id: Optional[str]
    status: str
    failure_count: int
    created_at: str
    updated_at: str
    version: int


class TriageCase(TypedDict, total=False):
    id: str
    patient_id: str
    channel: str
    severity: str
    disposition: Optional[str]
    diversion_success: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CostOfCareClaim(TypedDict, total=False):
    id: str
    center_id: str
    patient_id: str
    service_month: str
    category: str
    amount_cents: int
    adjudicated_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MonthlySettlement(TypedDict, total=False):
    id: str
    center_id: str
    period_month: str
    member_months: float
    accrued_revenue_cents: int
    total_cost_of_care_cents: int
    contribution_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OutreachEvent(TypedDict, total=False):
    id: str
    center_id: str
    event_label: str
    scheduled_on: str
    expected_attendance: int
    attributed_signups: int
    created_at: str
    updated_at: str
    version: int
