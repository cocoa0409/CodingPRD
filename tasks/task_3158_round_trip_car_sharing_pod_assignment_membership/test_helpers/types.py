"""Domain types: entity structures, status enums, role enum.

Field names are exactly as declared in the PRD. Every entity in this API carries
the full common-field set, so each TypedDict includes ``id``, ``created_at``,
``updated_at`` and ``version`` alongside its own fields.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    POD_OPERATOR = "PodOperator"
    UNIVERSITY_ACCOUNT_ADMIN = "UniversityAccountAdmin"
    FLEET_ADMIN = "FleetAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"


class MemberKind(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    STUDENT = "STUDENT"
    EMPLOYEE = "EMPLOYEE"


class ApplicationStatus(str, Enum):
    APPLIED = "APPLIED"
    SCREENING = "SCREENING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class ScreenResult(str, Enum):
    NONE = "NONE"
    CLEAR = "CLEAR"
    REFERRED = "REFERRED"
    FAILED = "FAILED"


class MembershipTier(str, Enum):
    STANDARD = "STANDARD"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"
    FROZEN = "FROZEN"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class AccountType(str, Enum):
    UNIVERSITY = "UNIVERSITY"
    BUSINESS = "BUSINESS"


class SiteType(str, Enum):
    NEIGHBORHOOD = "NEIGHBORHOOD"
    CAMPUS = "CAMPUS"
    AIRPORT = "AIRPORT"


class VehicleUseStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"
    CLEANING = "CLEANING"
    MAINTENANCE = "MAINTENANCE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class CleanlinessState(str, Enum):
    CLEAN = "CLEAN"
    REPORTED_DIRTY = "REPORTED_DIRTY"
    CLEANING = "CLEANING"
    ESCALATED = "ESCALATED"
    SUSPENDED_FOR_CLEANLINESS = "SUSPENDED_FOR_CLEANLINESS"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    IN_USE = "IN_USE"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class IncidentType(str, Enum):
    DAMAGE = "DAMAGE"
    MECHANICAL = "MECHANICAL"
    THEFT = "THEFT"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ASSESSED = "ASSESSED"
    FEE_CHARGED = "FEE_CHARGED"
    CLOSED = "CLOSED"


class InsuranceLayer(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class MaintenanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BLOCKED = "BLOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AccessMethod(str, Enum):
    KEY_CARD = "KEY_CARD"
    APP = "APP"


class AccessOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    LOCKOUT_REPORTED = "LOCKOUT_REPORTED"


class FuelTransactionStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class SignalType(str, Enum):
    CAMPUS = "CAMPUS"
    CLEANLINESS = "CLEANLINESS"
    AVAILABILITY = "AVAILABILITY"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECORDED = "RECORDED"


class RestoreStatus(str, Enum):
    PENDING = "PENDING"
    CONSUMED = "CONSUMED"


# ─── Entity shapes (PRD field names; all entities carry the common fields) ───


class Member(TypedDict):
    id: str
    full_name: str
    email: str
    kind: str
    application_status: str
    screen_result: str
    application_decided_at: Optional[str]
    last_accident_fee_block: int
    strikes: int
    referral_invites: int
    wallet_credit_cents: int
    wallet_hold_cents: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    name: str
    type: str
    primary_member_id: str
    billing_email: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    account_id: Optional[str]
    member_id: str
    department_code: str
    tier: str
    primary_flag: bool
    status: str
    status_before_freeze: Optional[str]
    membership_billing_cents: int
    residual_released_cents: int
    created_at: str
    updated_at: str
    version: int


class Pod(TypedDict):
    id: str
    name: str
    site_type: str
    capacity: int
    utilization_score: float
    available_bays: int
    fuel_floor_pct: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    pod_id: str
    vin: str
    model: str
    home_pod_id: Optional[str]
    capacity_seats: int
    odometer_miles: int
    next_service_miles: int
    use_status: str
    cleanliness_state: str
    fuel_level_pct: int
    last_known_odometer_at: Optional[str]
    charge_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    member_id: str
    pod_id: str
    vehicle_id: str
    reserved_hours: int
    start_at: str
    end_at: str
    returned_at: Optional[str]
    returned_pod_id: Optional[str]
    status: str
    reservation_at: Optional[str]
    closed_at: Optional[str]
    returned_odometer_miles: Optional[int]
    returned_fuel_level_pct: Optional[int]
    contamination_level: int
    charge_total_cents: Optional[int]
    late_minutes: int
    status_before_overdue: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    reservation_id: str
    vehicle_id: str
    member_id: str
    assigned_driver_member_id: Optional[str]
    incident_type: str
    repair_cost_cents: Optional[int]
    damage_fee_estimate_cents: Optional[int]
    member_damage_fee_cents: Optional[int]
    insurance_layer: Optional[str]
    fee_version: int
    damage_fee_charged: bool
    status: str
    assigned_damage_block_position: Optional[int]
    severity_score: int
    severity_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class MaintenanceOrder(TypedDict):
    id: str
    vehicle_id: str
    pod_id: str
    incident_id: Optional[str]
    reason: str
    blocking: bool
    scheduled_start: str
    scheduled_end: str
    status: str
    completed_at: Optional[str]
    released_cents: int
    created_at: str
    updated_at: str
    version: int


class AccessEvent(TypedDict):
    id: str
    reservation_id: str
    member_id: str
    vehicle_id: Optional[str]
    pod_id: Optional[str]
    method: str
    outcome: str
    occurred_at: Optional[str]
    auto_release_used: bool
    lockout_reported_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FuelCardTransaction(TypedDict):
    id: str
    reservation_id: str
    vehicle_id: str
    amount_cents: int
    gallons_hundredths: int
    fuel_level_after_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommunitySignal(TypedDict):
    id: str
    pod_id: str
    member_id: Optional[str]
    reservation_id: Optional[str]
    signal_type: str
    message: str
    created_at_signal: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DrivingRecordReport(TypedDict):
    id: str
    member_id: str
    license_state: str
    license_years_held: int
    report_status: str
    report_decision: str
    screen_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TierRestoreEntitlement(TypedDict):
    id: str
    membership_id: str
    tier: str
    reason: str
    restore_status: str
    consumed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PodShiftBundle(TypedDict):
    id: str
    source_pod_id: str
    dest_pod_id: str
    scheduled_start: str
    scheduled_end: str
    monthly_pods: List[str]
    bundle_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int