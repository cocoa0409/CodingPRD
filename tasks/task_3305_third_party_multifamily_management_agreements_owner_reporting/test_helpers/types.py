"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PORTFOLIO_MANAGER = "PortfolioManager"
    PROPERTY_ACCOUNTANT = "PropertyAccountant"
    OWNER_REP = "OwnerRep"
    REVENUE_ANALYST = "RevenueAnalyst"
    RISK_OFFICER = "RiskOfficer"


class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class TerminatedReason(str, Enum):
    CONVENIENCE = "CONVENIENCE"
    CAUSE = "CAUSE"
    DISPOSITION = "DISPOSITION"
    EXPIRY = "EXPIRY"


class ManagementPosture(str, Enum):
    UNMANAGED = "UNMANAGED"
    ONBOARDING = "ONBOARDING"
    MANAGED = "MANAGED"
    TRANSITIONING_OUT = "TRANSITIONING_OUT"
    DISPOSED = "DISPOSED"


class PropertyStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OnboardingStatus(str, Enum):
    INTAKE = "INTAKE"
    DATA_VERIFIED = "DATA_VERIFIED"
    LEDGER_IMPORTED = "LEDGER_IMPORTED"
    VENDOR_REVIEW = "VENDOR_REVIEW"
    READY = "READY"
    ACTIVATED = "ACTIVATED"
    ABORTED = "ABORTED"


class LeaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NOTICE = "NOTICE"
    VACATED = "VACATED"


class AssignmentStatus(str, Enum):
    PENDING = "PENDING"
    ASSUMED = "ASSUMED"
    ASSIGNED_TO_MANAGER = "ASSIGNED_TO_MANAGER"
    TERMINATED = "TERMINATED"


class BudgetKind(str, Enum):
    ANNUAL = "ANNUAL"
    REFORECAST = "REFORECAST"


class BudgetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PricingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PUBLISHED = "PUBLISHED"
    OWNER_OVERRIDDEN = "OWNER_OVERRIDDEN"
    WITHDRAWN = "WITHDRAWN"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class StatementBasis(str, Enum):
    CASH = "CASH"
    ACCRUAL = "ACCRUAL"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RESTATED = "RESTATED"


class LedgerKind(str, Enum):
    RENT = "RENT"
    FEE = "FEE"
    RECOVERY = "RECOVERY"
    CONCESSION = "CONCESSION"
    EXPENSE = "EXPENSE"
    PAYROLL = "PAYROLL"


class LedgerStatus(str, Enum):
    POSTED = "POSTED"
    VOID = "VOID"


class PackageType(str, Enum):
    MONTHLY_OWNER = "MONTHLY_OWNER"
    LENDER = "LENDER"


class PackageStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    DELIVERED = "DELIVERED"


class ClaimType(str, Enum):
    RESIDENT_INCIDENT = "RESIDENT_INCIDENT"
    EMPLOYMENT = "EMPLOYMENT"


class IndemnifiedBy(str, Enum):
    OWNER = "OWNER"
    MANAGER = "MANAGER"
    SHARED = "SHARED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class Owner(TypedDict, total=False):
    id: str
    legal_name: str
    distribution_day_of_month: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ManagementAgreement(TypedDict, total=False):
    id: str
    owner_id: str
    property_id: str
    base_fee_pct: float
    minimum_monthly_fee_cents: int
    incentive_threshold_egi_cents: int
    incentive_tier1_rate: float
    noi_hurdle_pct: float
    incentive_noi_share_pct: float
    tail_months: int
    tail_rate_pct: float
    effective_date: str
    term_end_date: str
    status: str
    terminated_reason: Optional[str]
    termination_fee_tail_cents: int
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    owner_id: str
    name: str
    unit_count: int
    management_posture: str
    disposition_listed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OnboardingTransition(TypedDict, total=False):
    id: str
    property_id: str
    prior_manager_name: str
    takeover_date: str
    status: str
    deposits_received_cents: int
    prepaid_rent_cents: int
    delinquency_cents: int
    net_position_cents: int
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict, total=False):
    id: str
    property_id: str
    unit_label: str
    full_name: str
    lease_end_date: str
    lease_status: str
    created_at: str
    updated_at: str
    version: int


class VendorContract(TypedDict, total=False):
    id: str
    property_id: str
    vendor_name: str
    service_type: str
    monthly_cost_cents: int
    start_date: str
    end_date: str
    assignment_status: str
    created_at: str
    updated_at: str
    version: int


class Budget(TypedDict, total=False):
    id: str
    property_id: str
    fiscal_year: int
    kind: str
    operating_revenue_cents: int
    operating_expense_cents: int
    capex_total_cents: int
    supersedes_budget_id: Optional[str]
    status: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PricingRecommendation(TypedDict, total=False):
    id: str
    property_id: str
    unit_label: str
    recommended_rent_cents: int
    effective_start_date: str
    effective_end_date: str
    status: str
    final_rent_cents: int
    override_rent_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StaffPosition(TypedDict, total=False):
    id: str
    property_id: str
    role_title: str
    hourly_cost_cents: int
    scheduled_hours_per_week: int
    shared_region_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MonthlyStatement(TypedDict, total=False):
    id: str
    property_id: str
    period_month: str
    basis: str
    collected_revenue_cents: int
    base_fee_cents: int
    incentive_fee_cents: int
    payroll_charge_cents: int
    management_fee_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    id: str
    property_id: str
    resident_id: Optional[str]
    kind: str
    amount_cents: int
    accrual_month: str
    collected_month: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OwnerReportPackage(TypedDict, total=False):
    id: str
    property_id: str
    period_month: str
    package_type: str
    distribution_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    property_id: str
    claim_type: str
    reserved_amount_cents: int
    indemnified_by: str
    incident_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.5): carries ONLY id + created_at; no updated_at, no version.
class ClaimSettlement(TypedDict, total=False):
    id: str
    claim_id: str
    amount_cents: int
    manager_share_cents: int
    owner_share_cents: int
    created_at: str
