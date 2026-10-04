"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ESCO_ENGINEER = "ESCOEngineer"
    OWNER_REP = "OwnerRep"
    LENDER_OFFICER = "LenderOfficer"


class ContractStatus(str, Enum):
    AUDIT = "AUDIT"
    SCOPED = "SCOPED"
    EXECUTED = "EXECUTED"
    CONSTRUCTION = "CONSTRUCTION"
    PERFORMANCE = "PERFORMANCE"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class BaselineStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"
    RESTATED = "RESTATED"
    REJECTED = "REJECTED"


class BundleStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    WITHDRAWN = "WITHDRAWN"


class MeasureStatus(str, Enum):
    PROPOSED = "PROPOSED"
    INCLUDED = "INCLUDED"
    INSTALLED = "INSTALLED"
    VERIFIED = "VERIFIED"
    EXCLUDED = "EXCLUDED"


class FacilityStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    FUNDING = "FUNDING"
    PAID_OFF = "PAID_OFF"
    CANCELLED = "CANCELLED"


class DrawStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class PhaseStatus(str, Enum):
    PLANNED = "PLANNED"
    MOBILIZED = "MOBILIZED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    SUSPENDED = "SUSPENDED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ATTESTED = "ATTESTED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"


class AdjustmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"


class PerformanceContract(TypedDict, total=False):
    id: str
    facility_name: str
    contract_term_years: int
    guarantee_start_date: str
    mv_protocol: str
    guaranteed_annual_savings_cents: int
    contract_value_cents: int
    guarantee_shortfall_reserve_cents: int
    cumulative_verified_savings_cents: int
    status: str
    executed_baseline_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Baseline(TypedDict, total=False):
    id: str
    contract_id: str
    baseline_period_start: str
    baseline_period_end: str
    annual_energy_kwh: int
    rate_schedule: list
    heating_degree_days: float
    cooling_degree_days: float
    occupancy_factor: float
    adjusted_annual_cost_cents: int
    status: str
    version_tag: int
    created_at: str
    updated_at: str
    version: int


class MeasureBundle(TypedDict, total=False):
    id: str
    contract_id: str
    name: str
    blended_payback_years: Optional[float]
    subsidy_pool_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Measure(TypedDict, total=False):
    id: str
    bundle_id: str
    contract_id: str
    measure_type: str
    installed_cost_cents: int
    annual_savings_cents: int
    simple_payback_years: Optional[float]
    subsidy_draw_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingFacility(TypedDict, total=False):
    id: str
    contract_id: str
    facility_type: str
    principal_cents: int
    annual_rate_pct: float
    term_years: int
    annual_payment_cents: int
    coverage_ratio: float
    drawn_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only log: carries ONLY id + created_at (no updated_at, no version)
class FinancingDraw(TypedDict, total=False):
    id: str
    facility_id: str
    amount_cents: int
    purpose: str
    status: str
    created_at: str


class WorkPhase(TypedDict, total=False):
    id: str
    contract_id: str
    phase_label: str
    window_start: str
    window_end: str
    disruption_budget_hours: int
    consumed_disruption_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only log: carries ONLY id + created_at (no updated_at, no version)
class DisruptionLog(TypedDict, total=False):
    id: str
    phase_id: str
    occurred_at: str
    hours: int
    cause: str
    created_at: str


class SavingsReport(TypedDict, total=False):
    id: str
    contract_id: str
    period_year: int
    actual_energy_kwh: int
    period_hdd: float
    period_cdd: float
    period_occupancy_factor: float
    verified_savings_cents: int
    shortfall_cents: int
    status: str
    attested_by_owner_rep_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BaselineAdjustment(TypedDict, total=False):
    id: str
    contract_id: str
    baseline_id: str
    supersedes_adjustment_id: Optional[str]
    reason: str
    kwh_delta: int
    occupancy_factor_override: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisputeNotice(TypedDict, total=False):
    id: str
    contract_id: str
    report_id: str
    filed_by_role: str
    claimed_savings_cents: int
    resolution_savings_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class OwnerRep(TypedDict, total=False):
    id: str
    full_name: str
    organization: str
    created_at: str
    updated_at: str
    version: int


class ESCOEngineer(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    created_at: str
    updated_at: str
    version: int
