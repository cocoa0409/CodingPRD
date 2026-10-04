"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SupplyContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class SupplyMode(str, Enum):
    DELIVERED_LIQUID = "DELIVERED_LIQUID"
    ON_SITE_GENERATION = "ON_SITE_GENERATION"
    PIPELINE = "PIPELINE"


class StationStatus(str, Enum):
    PLANNED = "PLANNED"
    PERMITTED = "PERMITTED"
    CONSTRUCTION = "CONSTRUCTION"
    COMMISSIONED = "COMMISSIONED"
    SUSPENDED = "SUSPENDED"


class LocationType(str, Enum):
    INDOOR = "INDOOR"
    OUTDOOR = "OUTDOOR"


class PermitStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PermitType(str, Enum):
    CONSTRUCTION = "CONSTRUCTION"
    FIRE = "FIRE"
    DISPENSING_INDOOR = "DISPENSING_INDOOR"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TransitionMode(str, Enum):
    PARALLEL = "PARALLEL"
    CUTOVER = "CUTOVER"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CertificationLevel(str, Enum):
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"
    MASTER = "MASTER"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class IncentiveType(str, Enum):
    FEDERAL_ITC = "FEDERAL_ITC"
    STATE_REBATE = "STATE_REBATE"
    UTILITY_GRANT = "UTILITY_GRANT"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CourseCode(str, Enum):
    H2_BASIC = "H2_BASIC"
    H2_OPERATOR = "H2_OPERATOR"
    H2_EMERGENCY = "H2_EMERGENCY"


class TrainingStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class MeasurementMode(str, Enum):
    TELEMATICS = "TELEMATICS"
    SELF_REPORTED = "SELF_REPORTED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SITE_MANAGER = "SiteManager"
    SAFETY_OFFICER = "SafetyOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CONVERSION_TECHNICIAN = "ConversionTechnician"
    BILLING_OPERATOR = "BillingOperator"


# All entities carry the standard system fields (PRD §2.4):
# id, created_at, updated_at, version.
class Site(TypedDict, total=False):
    id: str
    code: str
    name: str
    address: str
    status: str
    baseline_labor_rate_per_hour: float
    actual_productivity_units_per_hour: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict, total=False):
    id: str
    site_id: str
    forklift_count: int
    duty_cycle_hours_per_day: float
    peak_shift_hours: int
    daily_kg_estimate: float
    safety_findings_json: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyContract(TypedDict, total=False):
    id: str
    site_id: str
    supply_mode: str
    start_date: str
    end_date: str
    base_price_per_kg: float
    reliability_sla_pct: float
    committed_monthly_kg: float
    status: str
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FuelingStation(TypedDict, total=False):
    id: str
    site_id: str
    station_code: str
    location_type: str
    capacity_kg_per_day: float
    storage_capacity_kg: float
    construction_start: str
    construction_end: str
    construction_status: str
    commissioned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    station_id: str
    permit_type: str
    issued_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConversionPlan(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    target_forklift_count: int
    transition_mode: str
    start_date: str
    end_date: str
    status: str
    baseline_productivity_units_per_hour: float
    expected_productivity_gain_pct: float
    created_at: str
    updated_at: str
    version: int


class ConversionEvent(TypedDict, total=False):
    id: str
    conversion_plan_id: str
    forklift_id: str
    scheduled_start: str
    scheduled_end: str
    technician_id: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    name: str
    certification_level: str
    certified_until: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class ServiceAgreement(TypedDict, total=False):
    id: str
    site_id: str
    coverage_start: str
    coverage_end: str
    stack_replacement_included: bool
    availability_guarantee_pct: float
    monthly_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DowntimeReport(TypedDict, total=False):
    id: str
    site_id: str
    month: str
    forklift_id: str
    downtime_hours: float
    created_at: str
    updated_at: str
    version: int


class FuelingEvent(TypedDict, total=False):
    id: str
    station_id: str
    forklift_id: str
    occurred_at: str
    kg_dispensed: float
    supply_contract_id: str
    created_at: str
    updated_at: str
    version: int


class FuelInvoice(TypedDict, total=False):
    id: str
    site_id: str
    supply_contract_id: str
    period_start: str
    period_end: str
    total_kg: float
    subtotal_cents: int
    credit_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FuelLineItem(TypedDict, total=False):
    id: str
    invoice_id: str
    fueling_event_id: str
    kg: float
    unit_price_per_kg: float
    line_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class IncentiveClaim(TypedDict, total=False):
    id: str
    site_id: str
    incentive_type: str
    claimed_amount_cents: int
    qualification_date: str
    approved_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    id: str
    site_id: str
    trainee_employee_id: str
    course_code: str
    completed_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
