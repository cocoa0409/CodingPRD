"""Domain types for the Rideshare Rental Program API.

Entity TypedDicts, status enums and the caller-role enum. Every top-level
resource in the programme is fully versioned, so each TypedDict carries the
four system-managed properties: id, created_at, updated_at and version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Driver ───────────────────────────────────────────

class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    SUSPENDED = "SUSPENDED"


class LicenseClass(str, Enum):
    STANDARD = "STANDARD"
    FOR_HIRE = "FOR_HIRE"
    COMMERCIAL = "COMMERCIAL"


class ProgramDriverTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class Driver(TypedDict):
    id: str
    full_name: str
    email: str
    platform_driver_id: str
    platform_activity_score: int
    driving_record_points: int
    license_class: str
    program_driver_tier: str
    eligibility_status: str
    created_at: str
    updated_at: str
    version: int


# ─── DriverEnrollment ─────────────────────────────────

class EligibilityDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DEFERRED = "DEFERRED"


class EnrollmentStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class DriverEnrollment(TypedDict):
    id: str
    driver_id: str
    program_tier: str
    activity_snapshot: int
    record_snapshot: int
    eligibility_score: int
    eligibility_decision: str
    enrollment_status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── ProgramVehicle ───────────────────────────────────

class VehicleClass(str, Enum):
    STANDARD = "STANDARD"
    XL = "XL"
    LUXURY = "LUXURY"
    DELIVERY_VAN = "DELIVERY_VAN"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    MAINTENANCE = "MAINTENANCE"
    RECOVERY = "RECOVERY"
    RETIRED = "RETIRED"


class ProgramVehicle(TypedDict):
    id: str
    vin: str
    model_name: str
    model_year: int
    vehicle_class: str
    qualifies_ride: bool
    qualifies_delivery: bool
    odometer_miles: int
    baseline_odometer_miles: int
    vehicle_status: str
    assigned_driver_id: Optional[str]
    region_code: str
    created_at: str
    updated_at: str
    version: int


# ─── RentalAgreement ──────────────────────────────────

class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEWAL_DUE = "RENEWAL_DUE"
    DELINQUENT = "DELINQUENT"
    RECOVERY_PENDING = "RECOVERY_PENDING"
    RECOVERED = "RECOVERED"
    COMPLETED = "COMPLETED"
    PURCHASE_PENDING = "PURCHASE_PENDING"
    PURCHASED = "PURCHASED"


class RentalAgreement(TypedDict):
    id: str
    enrollment_id: str
    driver_id: str
    vehicle_id: str
    weekly_rate_cents: int
    insurance_premium_cents: int
    unlimited_mileage: bool
    mileage_cap_miles: Optional[int]
    maintenance_allowance_miles: int
    compliance_posture: str
    agreement_status: str
    current_week_number: int
    total_billed_cents: int
    total_waived_cents: int
    period_start: str
    period_end: str
    created_at: str
    updated_at: str
    version: int


# ─── RentalWeek ───────────────────────────────────────

class WeekStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    DUE = "DUE"
    PAID = "PAID"
    GRACE = "GRACE"
    DELINQUENT = "DELINQUENT"
    DEFERRED = "DEFERRED"
    RECOVERED = "RECOVERED"
    WAIVED = "WAIVED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class RentalWeek(TypedDict):
    id: str
    agreement_id: str
    vehicle_id: str
    week_number: int
    period_start: str
    period_end: str
    miles_driven: int
    base_charge_cents: int
    insurance_charge_cents: int
    mileage_overage_cents: int
    damage_charge_cents: int
    platform_credit_cents: int
    amount_due_cents: int
    week_status: str
    payment_status: str
    payment_deadline: Optional[str]
    grace_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── MaintenanceEvent ─────────────────────────────────

class MaintenanceEventType(str, Enum):
    SCHEDULED_SERVICE = "SCHEDULED_SERVICE"
    UNSCHEDULED_REPAIR = "UNSCHEDULED_REPAIR"
    DAMAGE_REPAIR = "DAMAGE_REPAIR"


class MaintenanceEventStatus(str, Enum):
    REPORTED = "REPORTED"
    IN_PROGRESS = "IN_PROGRESS"
    LOANER_ISSUED = "LOANER_ISSUED"
    COMPLETED = "COMPLETED"


class MaintenanceEvent(TypedDict):
    id: str
    agreement_id: str
    vehicle_id: str
    event_type: str
    odometer_at_service: int
    downtime_hours: int
    loaner_vehicle_id: Optional[str]
    loaner_deadline: Optional[str]
    event_status: str
    damage_liability_cents: int
    maintenance_allowance_applied_miles: int
    earnings_interruption_hours: int
    created_at: str
    updated_at: str
    version: int


# ─── RentalPayment ────────────────────────────────────

class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class RentalPayment(TypedDict):
    id: str
    agreement_id: str
    week_id: str
    amount_cents: int
    coverage_cents: int
    platform_credit_cents: int
    payment_outcome: str
    collected_at: str
    created_at: str
    updated_at: str
    version: int


# ─── PurchaseOption ───────────────────────────────────

class OptionStatus(str, Enum):
    OFFERED = "OFFERED"
    ELECTED = "ELECTED"
    ESCROW_FUNDED = "ESCROW_FUNDED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class PurchaseOption(TypedDict):
    id: str
    agreement_id: str
    driver_id: str
    option_status: str
    purchase_price_cents: int
    equity_credit_cents: int
    escrow_required_cents: int
    escrow_balance_cents: int
    escrow_weeks_required: int
    escrow_weeks_funded: int
    elected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── PlatformIntegration ──────────────────────────────

class IntegrationResult(str, Enum):
    QUALIFIED = "QUALIFIED"
    REJECTED_RIDE = "REJECTED_RIDE"
    REJECTED_DELIVERY = "REJECTED_DELIVERY"
    REJECTED_MODEL = "REJECTED_MODEL"


class PlatformIntegration(TypedDict):
    id: str
    agreement_id: str
    vehicle_id: str
    integration_result: str
    ride_qualified: bool
    delivery_qualified: bool
    model_restriction_hit: bool
    checked_at: str
    created_at: str
    updated_at: str
    version: int


# ─── FleetFact ────────────────────────────────────────

class FleetFactStatus(str, Enum):
    BALANCED = "BALANCED"
    UNDER_SUPPLIED = "UNDER_SUPPLIED"
    OVER_SUPPLIED = "OVER_SUPPLIED"


class FleetFact(TypedDict):
    id: str
    region_code: str
    demand_units: int
    active_agreements_count: int
    available_fleet_count: int
    utilization_bps: int
    sizing_deficit_units: int
    fleet_fact_status: str
    created_at: str
    updated_at: str
    version: int


# ─── Caller roles ─────────────────────────────────────

class UserRole(str, Enum):
    DRIVER = "Driver"
    FLEET_OPS_AGENT = "FleetOpsAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"
    SUPPORT_AGENT = "SupportAgent"


ALL_ROLES: List[str] = [r.value for r in UserRole]