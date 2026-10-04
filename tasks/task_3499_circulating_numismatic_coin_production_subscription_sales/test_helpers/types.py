"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3).

All fourteen resources carry the common property set (id, created_at,
updated_at, version) per PRD §2.5, so every TypedDict below includes them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    """The twelve declared roles, spelled exactly as the API expects them (PRD §2.1)."""
    ANONYMOUS = "Anonymous"
    PLATFORM_ADMIN = "PlatformAdmin"
    FED_LIAISON = "FedLiaison"
    PROCUREMENT_OFFICER = "ProcurementOfficer"
    PRODUCTION_PLANNER = "ProductionPlanner"
    QUALITY_INSPECTOR = "QualityInspector"
    DESTRUCTION_CERTIFIER = "DestructionCertifier"
    PROGRAM_MANAGER = "ProgramManager"
    MINT_DIRECTOR = "MintDirector"
    FINANCE_OFFICER = "FinanceOfficer"
    COLLECTOR = "Collector"
    BULLION_DEALER = "BullionDealer"


class FedOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCHEDULED = "SCHEDULED"
    FULFILLING = "FULFILLING"
    FULFILLED = "FULFILLED"
    SHORTFALL_RECORDED = "SHORTFALL_RECORDED"
    CANCELLED = "CANCELLED"


class LotStatus(str, Enum):
    ORDERED = "ORDERED"
    DELIVERED = "DELIVERED"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    STRIKING = "STRIKING"
    INSPECTION = "INSPECTION"  # transient; never persisted as a resting state
    REWORK = "REWORK"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProgramStatus(str, Enum):
    DESIGN_REVIEW = "DESIGN_REVIEW"
    APPROVED_FOR_SALE = "APPROVED_FOR_SALE"
    ON_SALE = "ON_SALE"
    SALES_CLOSED = "SALES_CLOSED"
    SURCHARGE_DISBURSED = "SURCHARGE_DISBURSED"


class ProductStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_SALE = "ON_SALE"
    SOLD_OUT = "SOLD_OUT"
    WITHDRAWN = "WITHDRAWN"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class OrderAllocationStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    WAITLISTED = "WAITLISTED"
    RELEASED = "RELEASED"


class OrderDerivedStatus(str, Enum):
    """Derived, never stored directly (PRD §3.6): CANCELLED iff RELEASED;
    COMPLETED iff PAID and ALLOCATED; else ACTIVE."""
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DUNNING = "DUNNING"
    CANCELLED = "CANCELLED"
    CANCELLED_NONPAYMENT = "CANCELLED_NONPAYMENT"


class InvoiceStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    WRITTEN_OFF = "WRITTEN_OFF"


class BullionIssueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SOLD_OUT = "SOLD_OUT"


class AuthorizedPurchaserStatus(str, Enum):
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AllocationStatus(str, Enum):
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    SETTLED = "SETTLED"
    EXPIRED = "EXPIRED"


class ErrorCoinCaseStatus(str, Enum):
    QUARANTINED = "QUARANTINED"
    DESTROYED = "DESTROYED"


class Commodity(str, Enum):
    COPPER = "COPPER"
    NICKEL = "NICKEL"
    ZINC = "ZINC"
    GOLD = "GOLD"
    SILVER = "SILVER"
    PLATINUM = "PLATINUM"


class BullionMetal(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    PLATINUM = "PLATINUM"


class Vault(str, Enum):
    WEST_POINT = "WEST_POINT"
    FORT_KNOX = "FORT_KNOX"
    DENVER_VAULT = "DENVER_VAULT"


class Facility(str, Enum):
    PHILADELPHIA = "PHILADELPHIA"
    DENVER = "DENVER"


class ProductType(str, Enum):
    PROOF_SET = "PROOF_SET"
    COMMEMORATIVE = "COMMEMORATIVE"
    UNCIRCULATED = "UNCIRCULATED"
    SUBSCRIPTION_SERIES = "SUBSCRIPTION_SERIES"


class SubscriptionFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class AuthorizedPurchaserTier(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class DesignDecision(str, Enum):
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class InspectionOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Denomination(TypedDict, total=False):
    id: str
    code: str
    face_value_cents: int
    blank_budget_cost_cents: float
    striking_cost_cents: float
    blanks_per_tonne: int
    blank_stock_pieces: int
    budgeted_unit_seigniorage_cents: float
    created_at: str
    updated_at: str
    version: int


class FederalReserveOrder(TypedDict, total=False):
    id: str
    fiscal_year: int
    denomination_code: str
    quantity_ordered_pieces: int
    due_date: str  # ISO 8601 calendar date
    status: str
    quantity_fulfilled_pieces: int
    budgeted_seigniorage_cents: float
    realized_seigniorage_cents: Optional[float]  # null until FULFILLED
    created_at: str
    updated_at: str
    version: int


class MetalProcurementLot(TypedDict, total=False):
    id: str
    commodity: str
    denomination_code: str
    quantity_tonnes: int
    budget_price_cents_per_tonne: int
    locked_unit_price_cents_per_tonne: Optional[int]  # absent means unhedged
    order_spot_cents_per_tonne: int
    vault: str
    planned_delivery_date: str  # ISO 8601 calendar date, metadata only
    status: str
    blanks_produced: int
    realized_cost_cents: Optional[int]  # null until DELIVERED
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    fed_order_id: str
    facility: str
    press_line: str
    planned_start: str  # domain datetime: renders as supplied
    planned_end: str
    planned_quantity: int
    status: str
    reserved_blanks: int
    produced_pieces: int
    scrapped_pieces: int
    rework_count: int
    created_at: str
    updated_at: str
    version: int


class CommemorativeProgram(TypedDict, total=False):
    id: str
    name: str
    statute_reference: str
    max_mintage_legal: int
    surcharge_cents_per_unit: int
    beneficiary_name: str
    beneficiary_cap_cents: int
    direct_costs_cents: int
    sales_window_start: str  # domain datetime
    sales_window_end: str
    status: str
    design_revision_count: int
    created_by_user_id: str
    gross_receipts_cents: int
    surcharge_accrued_cents: int
    net_proceeds_cents: int
    disbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class NumismaticProduct(TypedDict, total=False):
    id: str
    product_code: str
    program_id: Optional[str]
    product_family: str
    product_type: str
    price_cents: int
    mintage_limit: int
    household_order_limit: int
    release_datetime: str  # domain datetime
    subscription_eligible: bool
    status: str
    allocated_units: int
    remaining_units: int
    created_at: str
    updated_at: str
    version: int


class Collector(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    household_id: str
    created_at: str
    updated_at: str
    version: int


class NumismaticOrder(TypedDict, total=False):
    id: str
    collector_id: str
    product_id: str
    quantity: int
    total_cents: int
    payment_status: str
    allocation_status: str
    status: str  # derived
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    collector_id: str
    product_id: str
    units_per_cycle: int
    frequency: str
    status: str
    next_billing_date: str  # ISO 8601 calendar date
    cycles_billed: int
    created_at: str
    updated_at: str
    version: int


class SubscriptionInvoice(TypedDict, total=False):
    id: str
    subscription_id: str
    period_index: int
    amount_cents: int
    attempts: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BullionIssue(TypedDict, total=False):
    id: str
    name: str
    metal: str
    unit_weight_oz: float
    total_pool_units: int
    remaining_pool_units: int
    offer_window_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuthorizedPurchaser(TypedDict, total=False):
    id: str
    name: str
    tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BullionAllocation(TypedDict, total=False):
    id: str
    bullion_issue_id: str
    authorized_purchaser_id: str
    quantity_units: int
    offered_by_user_id: str
    offer_expires_at: str  # domain datetime: logical clock at creation + offer_window_hours
    total_price_cents: Optional[int]  # null until CONFIRMED
    status: str
    created_at: str
    updated_at: str
    version: int


class ErrorCoinCase(TypedDict, total=False):
    id: str
    production_run_id: str
    error_pieces: int
    description: Optional[str]
    reported_by_user_id: str
    status: str
    destroyed_by_user_ids: Optional[List[str]]  # null until DESTROYED
    created_at: str
    updated_at: str
    version: int
