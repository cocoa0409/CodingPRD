"""Domain types: entity TypedDicts, status enums and the role enum.

A sale line and a fund ledger entry are append-only: PRD 2.4 states that both
of these carry only `id` and `created_at`, so their TypedDicts deliberately
omit `updated_at` and `version`.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_OPERATOR = "SystemOperator"
    SURCHARGE_FUND_CONTROLLER = "SurchargeFundController"
    MWR_BOARD_OFFICER = "MwrBoardOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ASSORTMENT_PLANNER = "AssortmentPlanner"
    STORE_CASHIER = "StoreCashier"
    PATRON = "Patron"


class Channel(str, Enum):
    COMMISSARY = "COMMISSARY"
    EXCHANGE = "EXCHANGE"


class Region(str, Enum):
    CONUS = "CONUS"
    OVERSEAS = "OVERSEAS"
    DEPLOYED = "DEPLOYED"


class FundPosture(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    CONSTRAINED = "CONSTRAINED"
    FROZEN = "FROZEN"


class IdCardClass(str, Enum):
    ACTIVE_DUTY = "ACTIVE_DUTY"
    RETIREE = "RETIREE"
    DEPENDENT = "DEPENDENT"
    DISABLED_VETERAN = "DISABLED_VETERAN"
    GUARD_RESERVE = "GUARD_RESERVE"
    DOD_CIVILIAN_OVERSEAS = "DOD_CIVILIAN_OVERSEAS"


class CardStatus(str, Enum):
    VALID = "VALID"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class SuspensionReason(str, Enum):
    ADMIN_ACTION = "ADMIN_ACTION"
    SPONSOR_SUSPENDED = "SPONSOR_SUSPENDED"
    RISK_THRESHOLD = "RISK_THRESHOLD"


class ResaleWatchStatus(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    RESTRICTED = "RESTRICTED"


class CardAction(str, Enum):
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    REVOKE = "REVOKE"


class ComplianceDecision(str, Enum):
    CONFIRM_STRIKE = "CONFIRM_STRIKE"
    CLEAR_WATCH = "CLEAR_WATCH"


class DelegationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    SUSPENDED_BY_SPONSOR = "SUSPENDED_BY_SPONSOR"


class ProductCategory(str, Enum):
    GROCERY_STAPLE = "GROCERY_STAPLE"
    INFANT_FORMULA = "INFANT_FORMULA"
    TOBACCO = "TOBACCO"
    ALCOHOL = "ALCOHOL"
    GENERAL_MERCHANDISE = "GENERAL_MERCHANDISE"


class SupplyMode(str, Enum):
    WAREHOUSE = "WAREHOUSE"
    DSD = "DSD"


class AssortmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TenderState(str, Enum):
    OPEN = "OPEN"
    TENDERED = "TENDERED"
    VOIDED = "VOIDED"


class ComplianceState(str, Enum):
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class VoidedReason(str, Enum):
    RESALE_VIOLATION = "RESALE_VIOLATION"
    OPERATOR_ERROR = "OPERATOR_ERROR"
    COMPLIANCE_HOLD = "COMPLIANCE_HOLD"


class Fund(str, Enum):
    SURCHARGE = "SURCHARGE"
    DIVIDEND = "DIVIDEND"


class LedgerEntryType(str, Enum):
    SURCHARGE_COLLECTION = "SURCHARGE_COLLECTION"
    SURCHARGE_REVERSAL = "SURCHARGE_REVERSAL"
    CAPITAL_OUTLAY = "CAPITAL_OUTLAY"
    ALLOWANCE_CREDIT = "ALLOWANCE_CREDIT"
    ALLOWANCE_REVERSAL = "ALLOWANCE_REVERSAL"
    DIVIDEND_TRANSFER = "DIVIDEND_TRANSFER"


class SourceRefKind(str, Enum):
    SALE = "SALE"
    CAPITAL_PROJECT = "CAPITAL_PROJECT"
    MWR_PROGRAM = "MWR_PROGRAM"
    SPECIAL_ORDER = "SPECIAL_ORDER"


class ProjectState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    AWAITING_FUNDS = "AWAITING_FUNDS"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class ProjectDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"
    REJECT = "REJECT"


class MwrProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SpecialOrderState(str, Enum):
    SUBMITTED = "SUBMITTED"
    LOCAL_FILL_PENDING = "LOCAL_FILL_PENDING"
    OVERSEAS_SHIP_PENDING = "OVERSEAS_SHIP_PENDING"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class SpecialOrderRoute(str, Enum):
    LOCAL_FILL = "LOCAL_FILL"
    OVERSEAS_SHIP = "OVERSEAS_SHIP"


class CancelledReason(str, Enum):
    PATRON_REQUEST = "PATRON_REQUEST"
    ASSORTMENT_RETIRED = "ASSORTMENT_RETIRED"


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version
# ---------------------------------------------------------------------------


class Store(TypedDict):
    id: str
    name: str
    channel: str
    region: str
    surcharge_rate_bp: int
    exchange_markup_bp: int
    shelf_block_capacity_facings: int
    surcharge_fund_balance_cents: int
    surcharge_obligated_cents: int
    dividend_fund_balance_cents: int
    shipping_allowance_committed_cents: int
    fund_posture: str
    period_close_index: int
    created_at: str
    updated_at: str
    version: int


class Patron(TypedDict):
    id: str
    full_name: str
    id_card_class: str
    sponsor_patron_id: Optional[str]
    card_status: str
    suspension_reason: Optional[str]
    resale_watch_status: str
    resale_risk_score: int
    recent_sales_risk_score: int
    restricted_units_30d: int
    flagged_sale_count_30d: int
    manual_strike_count: int
    created_at: str
    updated_at: str
    version: int


class ShopperDelegation(TypedDict):
    id: str
    sponsor_patron_id: str
    delegate_patron_id: str
    valid_from: str
    valid_to: str
    per_sale_spend_cap_cents: int
    status: str
    superseded_by_delegation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    unit_cost_cents: int
    unit_weight_grams: int
    quantity_limit_per_visit: Optional[int]
    resale_restricted: bool
    created_at: str
    updated_at: str
    version: int


class Assortment(TypedDict):
    id: str
    store_id: str
    product_id: str
    shelf_block: str
    facings: int
    supply_mode: str
    vendor_name: Optional[str]
    promo_allowance_bp: int
    promo_window_start: Optional[str]
    promo_window_end: Optional[str]
    effective_from: str
    effective_to: str
    overseas_shipping_allowance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    store_id: str
    patron_id: str
    acting_delegation_id: Optional[str]
    business_date: str
    tender_state: str
    compliance_state: str
    line_count: int
    merchandise_cents: int
    markup_total_cents: int
    surcharge_total_cents: int
    tax_cents: int
    total_due_cents: int
    provisional_allowance_cents: int
    settled_allowance_cents: Optional[int]
    allowance_variance_cents: Optional[int]
    subsidized_shipping_cents: int
    voided_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapitalProject(TypedDict):
    id: str
    store_id: str
    title: str
    requested_amount_cents: int
    contingency_bp: int
    contingency_cents: int
    obligation_cents: int
    state: str
    revision_count: int
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    outlay_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MwrProgram(TypedDict):
    id: str
    store_id: str
    name: str
    priority_rank: int
    funding_ceiling_cents: int
    status: str
    ytd_funded_cents: int
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    store_id: str
    patron_id: str
    product_id: str
    quantity: int
    state: str
    route: Optional[str]
    billable_weight_kg: int
    gross_ship_cents: int
    patron_share_cents: int
    shipping_allowance_cents: int
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only records: id + created_at only, no updated_at and no version
# ---------------------------------------------------------------------------


class SaleLine(TypedDict):
    id: str
    sale_id: str
    product_id: str
    quantity: int
    unit_price_cents: int
    extended_cents: int
    line_markup_cents: int
    line_surcharge_cents: int
    line_allowance_cents: int
    line_shipping_allowance_cents: int
    restricted_units: int
    created_at: str


class FundLedgerEntry(TypedDict):
    id: str
    store_id: str
    fund: str
    entry_type: str
    amount_cents: int
    balance_after_cents: int
    period_close_index: int
    source_ref_kind: str
    source_ref_id: str
    created_at: str
