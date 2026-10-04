"""Domain types: entity TypedDicts, status enums, role enum.

Field sets mirror the resource descriptions in the PRD. Every entity carries
the common system-managed fields (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    FRANCHISOR_ADMIN = "FranchisorAdmin"
    FRANCHISE_FINANCE = "FranchiseFinance"
    OPERATOR = "Operator"
    COOP_MANAGER = "CoopManager"


class AcquisitionType(str, Enum):
    FEE_SIMPLE = "FEE_SIMPLE"
    GROUND_LEASE = "GROUND_LEASE"


class HoldingStatus(str, Enum):
    HELD = "HELD"
    COMMITTED = "COMMITTED"
    DIVESTED = "DIVESTED"


class OperatorStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CapacityGrade(str, Enum):
    STRONG = "STRONG"
    ADEQUATE = "ADEQUATE"
    WEAK = "WEAK"
    FAILING = "FAILING"


class StoreStatus(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    REPOSSESSED = "REPOSSESSED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    FEE_PENDING = "FEE_PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class SubleaseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    CURED = "CURED"
    REPOSSESSED = "REPOSSESSED"
    EXPIRED = "EXPIRED"


class SalesReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"


class RentChargeStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    WAIVED = "WAIVED"


class FundAssessmentStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    WAIVED = "WAIVED"


class ReinvestmentStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    SATISFIED = "SATISFIED"
    BREACHED = "BREACHED"


class DefaultEventStatus(str, Enum):
    DECLARED = "DECLARED"
    CURED = "CURED"
    REPOSSESSED = "REPOSSESSED"


class FundType(str, Enum):
    NATIONAL = "NATIONAL"
    LOCAL_COOP = "LOCAL_COOP"


class GovernanceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class CoopAssessmentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class CapacityReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


class Site(TypedDict, total=False):
    id: str
    site_code: str
    address: str
    acquisition_type: str
    ground_lease_expiry: Optional[str]
    holding_status: str
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict, total=False):
    id: str
    legal_name: str
    status: str
    fy_net_worth_cents: int
    fy_operating_income_cents: int
    capacity_score: Optional[int]
    capacity_grade: Optional[str]
    max_stores: int
    stores_operated_count: int
    delinquency_balance_cents: int
    escrow_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    store_code: str
    site_id: str
    operator_id: str
    status: str
    opened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FranchiseAgreement(TypedDict, total=False):
    id: str
    store_id: str
    operator_id: str
    initial_fee_cents: int
    royalty_rate: float
    ad_fund_rate: float
    occupancy_allocation_pct: float
    term_years: int
    term_start_date: str
    term_end_date: str
    renewal_of_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Sublease(TypedDict, total=False):
    id: str
    store_id: str
    operator_id: str
    base_rent_cents: int
    pct_rent_rate: float
    escalation_rate: float
    escalation_month: int
    escalation_day: int
    start_date: str
    end_date: str
    status: str
    active_default_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesReport(TypedDict, total=False):
    id: str
    store_id: str
    period_month: str
    gross_sales_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RentCharge(TypedDict, total=False):
    id: str
    store_id: str
    sublease_id: str
    billing_period: str
    period_start: str
    period_end: str
    escalation_count: int
    effective_base_rent_cents: int
    percentage_rent_cents: int
    annual_sales_cents: int
    selected_rent_cents: int
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundAssessment(TypedDict, total=False):
    id: str
    store_id: str
    agreement_id: str
    period_month: str
    occupancy_share_cents: int
    royalty_sales_cents: int
    royalty_cents: int
    ad_fund_cents: int
    provisional_royalty_cents: int
    final_royalty_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReinvestmentObligation(TypedDict, total=False):
    id: str
    store_id: str
    agreement_id: str
    required_budget_cents: int
    deadline_date: str
    min_spend_cents: int
    verified_spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DefaultEvent(TypedDict, total=False):
    id: str
    sublease_id: str
    store_id: str
    reason: str
    cure_fee_cents: int
    shortfall_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdvertisingFund(TypedDict, total=False):
    id: str
    name: str
    fund_type: str
    admin_fee_rate: float
    region_code: Optional[str]
    balance_cents: int
    governance_status: str
    created_at: str
    updated_at: str
    version: int


class CoopAssessment(TypedDict, total=False):
    id: str
    fund_id: str
    store_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityReview(TypedDict, total=False):
    id: str
    operator_id: str
    review_period: str
    active_defaults_count: int
    pending_reinvestment_count: int
    composite_score: int
    grade: str
    status: str
    created_at: str
    updated_at: str
    version: int
