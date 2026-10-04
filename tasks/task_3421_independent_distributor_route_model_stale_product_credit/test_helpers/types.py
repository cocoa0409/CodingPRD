"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3).

Every resource in the system carries the four system-managed fields of PRD §2.5:
id, created_at, updated_at, version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    COMPANY_ADMIN = "CompanyAdmin"
    ROUTE_OPS_MANAGER = "RouteOpsManager"
    CREDIT_ANALYST = "CreditAnalyst"
    DISTRIBUTOR = "Distributor"


# ---------------------------------------------------------------------------
# Status / enum vocabularies (PRD §3)
# ---------------------------------------------------------------------------

class TerritoryStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LISTED = "LISTED"
    UNDER_AGREEMENT = "UNDER_AGREEMENT"
    EXITING = "EXITING"


class DistributorStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    EXITED = "EXITED"


class ClassificationStatus(str, Enum):
    INDEPENDENT_CONTRACTOR = "INDEPENDENT_CONTRACTOR"
    DISPUTED = "DISPUTED"
    RECLASSIFIED_EMPLOYEE = "RECLASSIFIED_EMPLOYEE"


class AccountStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    PROBATION = "PROBATION"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED_SERVICE = "SUSPENDED_SERVICE"
    SUSPENDED_CLASSIFICATION = "SUSPENDED_CLASSIFICATION"
    EXITING = "EXITING"
    EXITED = "EXITED"


# Non-terminal agreement statuses for the overlap rule and the exit cascade
# (PRD §3.1, §3.8): every status except terminal EXITED.
NON_TERMINAL_AGREEMENT_STATUSES = (
    AgreementStatus.DRAFT.value,
    AgreementStatus.ACTIVE.value,
    AgreementStatus.SUSPENDED_SERVICE.value,
    AgreementStatus.SUSPENDED_CLASSIFICATION.value,
    AgreementStatus.EXITING.value,
)


class SuspensionReason(str, Enum):
    SERVICE_DEFAULT = "SERVICE_DEFAULT"
    CLASSIFICATION_DISPUTE = "CLASSIFICATION_DISPUTE"


class FinancierType(str, Enum):
    COMPANY = "COMPANY"
    EXTERNAL_LENDER = "EXTERNAL_LENDER"


class FinancingPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    PAID_OFF = "PAID_OFF"
    SUPERSEDED = "SUPERSEDED"
    SETTLED_ON_EXIT = "SETTLED_ON_EXIT"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


WEEKDAY_VALUES = [w.value for w in Weekday]


class ProductionDayStatus(str, Enum):
    PLANNING = "PLANNING"
    CLOSED = "CLOSED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class CancelledReason(str, Enum):
    DISTRIBUTOR_CANCELLED = "DISTRIBUTOR_CANCELLED"
    AGREEMENT_SUSPENDED = "AGREEMENT_SUSPENDED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CREDIT_ISSUED = "CREDIT_ISSUED"


class DenialReason(str, Enum):
    DENIED_BY_REVIEW = "DENIED_BY_REVIEW"
    AUTO_EXPIRED = "AUTO_EXPIRED"


class ClaimDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    REQUEST_INFO = "REQUEST_INFO"


class ReinstateResolution(str, Enum):
    CONFIRMED_IC = "CONFIRMED_IC"
    RECLASSIFIED = "RECLASSIFIED"


class TransferMode(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    FOR_CAUSE = "FOR_CAUSE"


class TransferStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5 common fields on every resource)
# ---------------------------------------------------------------------------

class CatalogEntry(TypedDict):
    sku: str
    display_name: str
    shelf_life_days: int
    list_price_cents: int


class Bakery(TypedDict):
    id: str
    name: str
    daily_capacity_units: int
    product_catalog: List[CatalogEntry]
    created_at: str
    updated_at: str
    version: int


class Territory(TypedDict):
    id: str
    area_code: str
    list_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Distributor(TypedDict):
    id: str
    legal_name: str
    credit_limit_cents: int
    status: str
    classification_status: str
    account_standing: str
    trade_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class RouteAgreement(TypedDict):
    id: str
    territory_id: str
    distributor_id: str
    bakery_id: str
    purchase_price_cents: int
    financed_amount_cents: int
    discount_pct: float
    start_date: str
    end_date: str
    status: str
    suspension_reason: Optional[str]
    strike_count: int
    activated_on: Optional[str]
    exited_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancingPlan(TypedDict):
    id: str
    agreement_id: str
    financier_type: str
    lender_name: Optional[str]
    principal_cents: int
    annual_interest_rate: float
    term_weeks: int
    weekly_payment_cents: Optional[int]
    disburse_date: Optional[str]
    outstanding_principal_cents: Optional[int]
    total_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditEntry(TypedDict):
    audit_date: str
    shelf_stock_score: int
    rotation_score: int
    display_score: int
    composite_score: int
    is_violation: bool


class RetailAccount(TypedDict):
    id: str
    distributor_id: str
    store_name: str
    delivery_weekdays: List[str]
    compliance_score: Optional[int]
    last_audit_on: Optional[str]
    audit_log: List[AuditEntry]
    created_at: str
    updated_at: str
    version: int


class ProductionDay(TypedDict):
    id: str
    bakery_id: str
    date: str
    capacity_units: int
    allocated_units: int
    forecast_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    sku: str
    qty: int


class DailyOrder(TypedDict):
    id: str
    distributor_id: str
    delivery_date: str
    lines: List[OrderLine]
    units_total: int
    status: str
    submitted_on: Optional[str]
    delivered_lines: Optional[List[OrderLine]]
    total_charge_cents: Optional[int]
    verified_lines: Optional[List[OrderLine]]
    shortage_credit_cents: int
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimItem(TypedDict):
    sku: str
    delivery_date: str
    pulled_qty: int
    pull_date: str


class StaleReturnClaim(TypedDict):
    id: str
    distributor_id: str
    items: List[ClaimItem]
    status: str
    provisional_credit_cents: int
    approved_credit_cents: Optional[int]
    issued_credit_cents: Optional[int]
    cap_truncated_cents: Optional[int]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ValuationDetail(TypedDict):
    depreciation_cents: int
    goodwill_cents: int
    penalty_cents: int


class TerritoryTransfer(TypedDict):
    id: str
    agreement_id: str
    mode: str
    gross_valuation_cents: int
    valuation_detail: ValuationDetail
    financing_payoff_cents: Optional[int]
    distributor_payout_cents: Optional[int]
    status: str
    settled_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementStatement(TypedDict):
    week: str
    gross_charges_cents: int
    stale_credits_issued_cents: int
    net_trade_cents: int
    stale_cap_cents: int
    stale_cap_used_cents: int
    trade_balance_cents: int
    ledger_view_cents: int
    document_view_cents: int
    reconciles: bool
