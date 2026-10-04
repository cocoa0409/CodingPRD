"""Domain types: entity TypedDicts, lifecycle enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    SETTLEMENT_ANALYST = "SettlementAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SERVICE_PROVIDER = "ServiceProvider"
    ANONYMOUS = "Anonymous"


class ServiceProviderStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class ServiceAreaStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    ARCHIVED = "ARCHIVED"


class RouteAssignmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PENDING_TRANSFER = "PENDING_TRANSFER"
    TRANSFERRED = "TRANSFERRED"
    TERMINATED = "TERMINATED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    RE_NEGOTIATION = "RE_NEGOTIATION"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class VehicleStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class DriverStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class InsurancePolicyStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class SettlementPeriodStatus(str, Enum):
    OPEN = "OPEN"
    ACCRUAL_CLOSED = "ACCRUAL_CLOSED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"
    RELEASED = "RELEASED"


class ChargebackClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SETTLED = "SETTLED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    COUNTERED = "COUNTERED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"


class PeakSeasonDeclarationStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELED = "CANCELED"


# ── Entities carrying the full common field set (id, created_at, updated_at, version) ──

class ServiceProvider(TypedDict):
    id: str
    legal_name: str
    provider_type: str
    tax_id: str
    brand_compliance_pct: float
    qualification_pct: float
    safety_index: float
    lifetime_paid_cents: int
    chargeback_outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceArea(TypedDict):
    id: str
    area_code: str
    state_code: str
    zip_prefix_low: str
    zip_prefix_high: str
    stop_capacity_weekly: int
    assigned_provider_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteAssignment(TypedDict):
    id: str
    service_area_id: str
    provider_id: str
    acquiring_provider_id: Optional[str]
    superseded_by_assignment_id: Optional[str]
    effective_date: str
    transfer_price_cents: int
    occupancy_ends_at: Optional[str]
    compliance_failures_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict):
    id: str
    provider_id: str
    service_area_id: str
    base_rate_cents_per_stop: int
    package_rate_cents: int
    peak_surcharge_cents: int
    insurance_coverage_cents: int
    negotiated_by: str
    renewal_due_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    provider_id: str
    service_area_id: str
    vehicle_class: str
    gvwr_pounds: int
    is_temporary: bool
    branding_compliance: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    provider_id: str
    service_area_id: str
    full_name: str
    license_class: str
    qualification_status: str
    is_temporary: bool
    duty_window_starts_at: Optional[str]
    duty_window_ends_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    provider_id: str
    policy_type: str
    coverage_cents: int
    expires_at: str
    verified_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementPeriod(TypedDict):
    id: str
    provider_id: str
    service_area_id: str
    week_start_at: str
    is_peak_week: bool
    fuel_rate_cents_per_mile: int
    base_gross_cents: int
    net_amount_cents: int
    performance_multiplier: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceMetric(TypedDict):
    id: str
    provider_id: str
    service_score: float
    safety_score: float
    customer_experience_score: float
    composite_score: float
    renewal_recommendation: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChargebackClaim(TypedDict):
    id: str
    provider_id: str
    settlement_period_id: str
    vehicle_id: Optional[str]
    claim_type: str
    amount_cents: int
    net_of_recovery_cents: Optional[int]
    recovery_rate_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PeakSeasonDeclaration(TypedDict):
    id: str
    service_area_id: str
    declaration_code: str
    starts_on: str
    ends_on: str
    authorized_vehicles: int
    authorized_drivers: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FuelIndexRate(TypedDict):
    id: str
    region_state_code: str
    effective_on: str
    rate_cents_per_mile: int
    published_by: str
    created_at: str
    updated_at: str
    version: int


# ── Entities declared WITHOUT the common field set (id + created_at only) ──

class StopObservation(TypedDict):
    id: str
    settlement_period_id: str
    observed_date: str
    recorded_at: str
    stops_count: int
    packages_count: int
    miles_driven: int
    accessorial_cents: int
    created_at: str
    # no updated_at, no version — append-only log


class SettlementDeduction(TypedDict):
    id: str
    settlement_period_id: str
    deduction_type: str
    amount_cents: int
    chargeback_category: Optional[str]
    performance_factor_eligible: bool
    created_at: str
    # no updated_at, no version — append-only log


class Dispute(TypedDict):
    id: str
    settlement_period_id: str
    filed_by_role: str
    disputed_amount_cents: int
    reason_code: str
    rounds_used: int
    opened_at: str
    expires_at: str
    status: str
    created_at: str
    # no updated_at, no version — declared without common fields