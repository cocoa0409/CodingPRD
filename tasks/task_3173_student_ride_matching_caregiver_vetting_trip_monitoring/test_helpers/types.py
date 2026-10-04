"""Domain types for the Student Ride Matching API.

Entity TypedDicts, status enums and the role enum, derived from the PRD's
resource model (§2.7 declares that every resource carries ``id``,
``created_at``, ``updated_at`` and ``version``).
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    DISTRICT_ADMIN = "DistrictAdmin"
    DRIVER = "Driver"
    SUPPORT_CENTER_AGENT = "SupportCenterAgent"
    PLATFORM_ADMIN = "PlatformAdmin"


class ProgramType(str, Enum):
    FOSTER_CARE = "FOSTER_CARE"
    HOMELESS_MCKINNEY_VENTO = "HOMELESS_MCKINNEY_VENTO"
    SPECIAL_EDUCATION = "SPECIAL_EDUCATION"
    GENERAL = "GENERAL"


class RiderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class VehicleClass(str, Enum):
    SEDAN = "SEDAN"
    SUV = "SUV"
    WHEELCHAIR_VAN = "WHEELCHAIR_VAN"


class ChildSeatType(str, Enum):
    NONE = "NONE"
    BOOSTER = "BOOSTER"
    HARNESS = "HARNESS"
    INTEGRATED = "INTEGRATED"


class DriverStatus(str, Enum):
    PENDING = "PENDING"
    BACKGROUND_CHECK = "BACKGROUND_CHECK"
    INSPECTION = "INSPECTION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class BackgroundCheckType(str, Enum):
    FINGERPRINT_FBI = "FINGERPRINT_FBI"
    FINGERPRINT_STATE = "FINGERPRINT_STATE"
    COUNTY_COURT = "COUNTY_COURT"
    SEX_OFFENDER_REGISTRY = "SEX_OFFENDER_REGISTRY"


class BackgroundCheckResult(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FAILED = "FAILED"


class InspectionResult(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class BillingPeriod(str, Enum):
    WEEKLY = "WEEKLY"
    SEMI_MONTHLY = "SEMI_MONTHLY"
    MONTHLY = "MONTHLY"


class TripType(str, Enum):
    AM_SCHOOL = "AM_SCHOOL"
    PM_SCHOOL = "PM_SCHOOL"
    MIDDAY = "MIDDAY"
    ACTIVITY = "ACTIVITY"


class RequiredSpecialty(str, Enum):
    NONE = "NONE"
    CAREGIVER_REQUIRED = "CAREGIVER_REQUIRED"
    WHEELCHAIR = "WHEELCHAIR"


class RideRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    SERIES_SUSPENDED = "SERIES_SUSPENDED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class TripState(str, Enum):
    SCHEDULED = "SCHEDULED"
    DRIVER_EN_ROUTE = "DRIVER_EN_ROUTE"
    AWAITING_STUDENT = "AWAITING_STUDENT"
    STUDENT_ONBOARD = "STUDENT_ONBOARD"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SafetyState(str, Enum):
    NORMAL = "NORMAL"
    DISCREPANCY = "DISCREPANCY"
    LOCKED = "LOCKED"


class TripExceptionCode(str, Enum):
    RIDER_NOT_PRESENT = "RIDER_NOT_PRESENT"
    RIDER_REFUSED_BOARDING = "RIDER_REFUSED_BOARDING"
    UNAUTHORIZED_DROPOFF = "UNAUTHORIZED_DROPOFF"


class HandoffLeg(str, Enum):
    PICKUP = "PICKUP"
    DROPOFF = "DROPOFF"


class HandoffExpectedParty(str, Enum):
    SCHOOL_STAFF = "SCHOOL_STAFF"
    AUTHORIZED_ADULT = "AUTHORIZED_ADULT"
    PLACEMENT_WORKER = "PLACEMENT_WORKER"


class HandoffVerificationMethod(str, Enum):
    PHOTO_ID = "PHOTO_ID"
    PIN = "PIN"
    PHYSICAL_SIGNATURE = "PHYSICAL_SIGNATURE"


class HandoffResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class IncidentCategory(str, Enum):
    NO_SHOW_UNVERIFIED = "NO_SHOW_UNVERIFIED"
    DRIVER_MISCONDUCT = "DRIVER_MISCONDUCT"
    VEHICLE_UNSAFE = "VEHICLE_UNSAFE"
    HANDOFF_DISPUTE = "HANDOFF_DISPUTE"
    STUDENT_DISTRESS = "STUDENT_DISTRESS"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class IncidentAdjudication(str, Enum):
    DRIVER_AT_FAULT = "DRIVER_AT_FAULT"
    NO_FAULT = "NO_FAULT"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    VOIDED = "VOIDED"


class AlertType(str, Enum):
    TRIP_DELAY = "TRIP_DELAY"
    GEOFENCE_BREACH = "GEOFENCE_BREACH"
    HANDOFF_DISPUTE = "HANDOFF_DISPUTE"
    STUDENT_ABSENT = "STUDENT_ABSENT"


class AlertSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every resource carries id/created_at/updated_at/version
# ---------------------------------------------------------------------------

class District(TypedDict):
    id: str
    name: str
    billing_email: str
    contract_rate_per_ride_cents: int
    contract_rate_per_mile_cents: int
    minimum_billable_cents: int
    no_school_dates: List[str]
    bell_schedule_start: str
    support_center_alert_enabled: bool
    outstanding_balance_cents: int
    credit_balance_cents: int
    account_status: str
    trips_scheduled_total: int
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict):
    id: str
    district_id: str
    full_name: str
    date_of_birth: str
    program_type: str
    spi_level: int
    home_address: str
    school_name: str
    emergency_contact_phone: str
    authorized_adults: List[dict]
    notify_on_pickup: bool
    notify_on_dropoff: bool
    support_center_phone_masked: str
    active_ride_request_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    full_name: str
    phone: str
    employer_org: str
    caregiver_experience_months: int
    language_codes: List[str]
    vehicle_class: str
    seat_capacity: int
    child_seat_type: str
    approved_seat_count: int
    compliance_expires_at: Optional[str]
    incident_strike_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict):
    id: str
    driver_id: str
    check_type: str
    reference_code: str
    result: str
    expires_on: str
    cleared_after_months: Optional[int]
    created_at: str
    updated_at: str
    version: int


class VehicleInspection(TypedDict):
    id: str
    driver_id: str
    vehicle_class: str
    seat_count: int
    child_seat_type: str
    inspector_note: str
    result: str
    expires_on: str
    seat_credit: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    district_id: str
    effective_from: str
    through_date: str
    per_ride_rate_cents: int
    per_mile_rate_cents: int
    minimum_billable_cents: int
    billing_period: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RideRequest(TypedDict):
    id: str
    district_id: str
    rider_id: str
    trip_type: str
    required_specialty: str
    window_start_at: str
    window_end_at: str
    max_window_minutes: int
    min_lead_time_hours: int
    pickup_address: str
    dropoff_address: str
    is_recurring: bool
    days_of_week: List[int]
    series_effective_from: Optional[str]
    series_through_date: Optional[str]
    series_no_school_dates: List[str]
    revision_count: int
    status: str
    recurring_series_active: bool
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict):
    id: str
    district_id: str
    ride_request_id: str
    rider_id: str
    driver_id: Optional[str]
    scheduled_date: str
    window_start_at: str
    window_end_at: str
    pickup_address: str
    dropoff_address: str
    trip_state: str
    safety_state: str
    candidate_driver_id: Optional[str]
    claimed_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    verified_authorized_adult_name: Optional[str]
    billable_ride_units: int
    planned_miles: float
    billable_miles: float
    billing_period_key: str
    exception_code: Optional[str]
    exception_recorded_at: Optional[str]
    accepted_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HandoffVerification(TypedDict):
    id: str
    trip_id: str
    leg: str
    expected_party: str
    verified_party_name: str
    verification_method: str
    verification_code: Optional[str]
    authorized: bool
    result: str
    captured_at: str
    created_at: str
    updated_at: str
    version: int


class SafetyIncident(TypedDict):
    id: str
    trip_id: str
    driver_id: Optional[str]
    category: str
    severity: str
    reported_by_actor: str
    summary: str
    adjudication: Optional[str]
    resolution_note: Optional[str]
    student_impact_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TripAlert(TypedDict):
    id: str
    trip_id: str
    source_incident_id: Optional[str]
    alert_type: str
    severity: str
    notify_caregiver: bool
    notify_school: bool
    notify_support_center: bool
    status: str
    released_by_resolution: bool
    created_at: str
    updated_at: str
    version: int


class Geofence(TypedDict):
    id: str
    district_id: str
    label: str
    center_lat: float
    center_lon: float
    radius_miles: float
    registered_on: str
    created_at: str
    updated_at: str
    version: int


class GeofenceCheck(TypedDict):
    id: str
    trip_id: str
    geofence_id: str
    observed_at: str
    observed_lat: float
    observed_lon: float
    inside: bool
    breach_alert_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingStatement(TypedDict):
    id: str
    district_id: str
    contract_id: str
    period_key: str
    period_start: str
    period_end: str
    total_ride_units: int
    total_miles: float
    total_amount_cents: int
    applied_credit_cents: int
    issued_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole", "ProgramType", "RiderStatus", "VehicleClass", "ChildSeatType",
    "DriverStatus", "BackgroundCheckType", "BackgroundCheckResult",
    "InspectionResult", "ContractStatus", "BillingPeriod", "TripType",
    "RequiredSpecialty", "RideRequestStatus", "TripState", "SafetyState",
    "TripExceptionCode", "HandoffLeg", "HandoffExpectedParty",
    "HandoffVerificationMethod", "HandoffResult", "IncidentCategory",
    "IncidentSeverity", "IncidentAdjudication", "IncidentStatus", "AlertType",
    "AlertSeverity", "AlertStatus", "StatementStatus", "AccountStatus",
    "District", "Rider", "Driver", "BackgroundCheck", "VehicleInspection",
    "Contract", "RideRequest", "Trip", "HandoffVerification", "SafetyIncident",
    "TripAlert", "Geofence", "GeofenceCheck", "BillingStatement",
]