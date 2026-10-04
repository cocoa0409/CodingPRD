"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class PlanTierCode(str, Enum):
    EMERGENCY_ONLY = "EMERGENCY_ONLY"
    SAFETY = "SAFETY"
    SAFETY_REMOTE = "SAFETY_REMOTE"
    PREMIUM = "PREMIUM"


class PlanTierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    STOLEN_REPORTED = "STOLEN_REPORTED"
    RECOVERED = "RECOVERED"
    DECOMMISSIONED = "DECOMMISSIONED"


class SubscriptionStatus(str, Enum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    LAPSED = "LAPSED"
    EMERGENCY_RETAINED = "EMERGENCY_RETAINED"
    CANCELLED = "CANCELLED"


class CrashEventStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ADVISOR_CONNECTED = "ADVISOR_CONNECTED"
    DISPATCH_COORDINATED = "DISPATCH_COORDINATED"
    CLOSED_NO_INJURY = "CLOSED_NO_INJURY"
    CLOSED_DISPATCHED = "CLOSED_DISPATCHED"
    REJECTED_NO_COVERAGE = "REJECTED_NO_COVERAGE"
    REJECTED_NO_ENTITLEMENT = "REJECTED_NO_ENTITLEMENT"


class SeverityBand(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class DispatchRequestStatus(str, Enum):
    PENDING = "PENDING"
    LOCATION_SENT = "LOCATION_SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CANCELLED = "CANCELLED"


class PSAPStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class StolenVehicleCaseStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    SLOWDOWN_ARMED = "SLOWDOWN_ARMED"
    SLOWDOWN_EXECUTED = "SLOWDOWN_EXECUTED"
    CLOSED_RECOVERED = "CLOSED_RECOVERED"
    CLOSED_UNVERIFIED = "CLOSED_UNVERIFIED"


class RemoteCommandType(str, Enum):
    LOCK = "LOCK"
    UNLOCK = "UNLOCK"
    HORN_LIGHTS = "HORN_LIGHTS"
    LOCATE = "LOCATE"


class RemoteCommandStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class DiagnosticReportStatus(str, Enum):
    GENERATED = "GENERATED"
    SERVICE_SCHEDULED = "SERVICE_SCHEDULED"


class DealerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ServiceAppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ConsentType(str, Enum):
    DRIVING_DATA_COLLECTION = "DRIVING_DATA_COLLECTION"
    INSURANCE_PROGRAM_SHARING = "INSURANCE_PROGRAM_SHARING"


class ConsentStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT = "Account"
    ADVISOR = "Advisor"
    PSAP_OPERATOR = "PSAPOperator"
    LAW_ENFORCEMENT = "LawEnforcement"
    EMERGENCY_OPERATOR = "EmergencyOperator"
    DEALER_SERVICE = "DealerService"
    BILLING_ADMIN = "BillingAdmin"
    SYSTEM_INGESTION = "SystemIngestion"


class PlanTier(TypedDict):
    id: str
    code: str
    monthly_fee_cents: int
    allows_emergency: bool
    allows_remote_commands: bool
    allows_navigation: bool
    allows_data_gb: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    home_region_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    account_id: str
    vin: str
    make: str
    model: str
    model_year: int
    region_code: str
    hardware_generation: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    account_id: str
    vehicle_id: str
    tier_code: str
    status: str
    trial_start_date: str
    trial_end_date: str
    current_period_start: str
    next_renewal_date: Optional[str]
    lapse_date: Optional[str]
    emergency_only_flag: bool
    period_remote_commands_used: int
    conversion_fee_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class CoverageZone(TypedDict):
    id: str
    region_code: str
    has_cellular: bool
    supports_data: bool
    supports_navigation: bool
    created_at: str
    updated_at: str
    version: int


class CrashEvent(TypedDict):
    id: str
    vehicle_id: str
    subscription_id: Optional[str]
    delta_v_kph: float
    rollover_detected: bool
    airbag_deployed: bool
    location_region_code: str
    severity_score: float
    severity_band: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DispatchRequest(TypedDict):
    id: str
    crash_event_id: str
    psap_id: str
    status: str
    location_payload: Optional[dict]
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PSAP(TypedDict):
    id: str
    name: str
    region_code: str
    accepts_location_transfer: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class StolenVehicleCase(TypedDict):
    id: str
    vehicle_id: str
    police_report_number: str
    reporting_agency: str
    status: str
    verified_by_user_id: Optional[str]
    slowdown_executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemoteCommand(TypedDict):
    id: str
    vehicle_id: str
    subscription_id: Optional[str]
    command_type: str
    status: str
    is_emergency_command: bool
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class DiagnosticReport(TypedDict):
    id: str
    vehicle_id: str
    odometer_km: int
    engine_hours: int
    dtc_codes: List[str]
    oil_life_pct: int
    health_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict):
    id: str
    name: str
    region_code: str
    service_capacity_per_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAppointment(TypedDict):
    id: str
    dealer_id: str
    vehicle_id: str
    diagnostic_report_id: str
    scheduled_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DataConsent(TypedDict):
    id: str
    account_id: str
    consent_type: str
    status: str
    granted_at: str
    revoked_at: Optional[str]
    effective_score: Optional[float]
    created_at: str
    updated_at: str
    version: int
