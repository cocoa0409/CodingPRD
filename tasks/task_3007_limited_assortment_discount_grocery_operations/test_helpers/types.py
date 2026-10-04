"""Domain types for the Limited-Assortment Grocery API.

Status enums for every entity lifecycle, the eight acting roles, and
TypedDicts describing each resource's wire shape. Entities with the common
field set carry id/created_at/updated_at/version; the append-only cart coin
ledger entry carries only id/created_at.
"""

from enum import Enum
from typing import Optional, TypedDict


class CategoryStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProductKind(str, Enum):
    CORE = "CORE"
    FINDS = "FINDS"


class ProductStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class TenderStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EVALUATING = "EVALUATING"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ELIGIBLE = "ELIGIBLE"
    DISQUALIFIED = "DISQUALIFIED"
    AWARDED_PRIMARY = "AWARDED_PRIMARY"
    AWARDED_SECONDARY = "AWARDED_SECONDARY"
    NOT_SELECTED = "NOT_SELECTED"


class PanelStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SCORED = "SCORED"
    LOCKED = "LOCKED"


class StoreTier(str, Enum):
    STANDARD = "STANDARD"
    HIGH_VOLUME = "HIGH_VOLUME"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class EmployeeRole(str, Enum):
    CASHIER = "CASHIER"
    STOCKER = "STOCKER"
    SHIFT_LEAD = "SHIFT_LEAD"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class FindsBuyStatus(str, Enum):
    PLANNED = "PLANNED"
    ALLOCATED = "ALLOCATED"
    ON_SALE = "ON_SALE"
    SOLD_OUT = "SOLD_OUT"
    CLOSED = "CLOSED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    ON_SALE = "ON_SALE"
    SOLD_OUT = "SOLD_OUT"
    CLEARANCE = "CLEARANCE"
    CLOSED = "CLOSED"


class CartCoinEventType(str, Enum):
    INSERT = "INSERT"
    RETURN = "RETURN"
    CORRAL_COLLECT = "CORRAL_COLLECT"
    AUDIT_ADJUST = "AUDIT_ADJUST"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ShiftCompliance(str, Enum):
    COMPLIANT = "COMPLIANT"
    BELOW_STANDARD = "BELOW_STANDARD"


class LaborWindowStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class ClaimReason(str, Enum):
    QUALITY_DEFECT = "QUALITY_DEFECT"
    DAMAGED = "DAMAGED"
    OTHER = "OTHER"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    RESCINDED = "RESCINDED"


class UserRole(str, Enum):
    OPERATIONS_ADMIN = "OperationsAdmin"
    CATEGORY_MANAGER = "CategoryManager"
    PROCUREMENT_LEAD = "ProcurementLead"
    QUALITY_ASSURANCE_LEAD = "QualityAssuranceLead"
    SUPPLIER_REP = "SupplierRep"
    STORE_MANAGER = "StoreManager"
    CASHIER = "Cashier"
    CUSTOMER_SERVICE_AGENT = "CustomerServiceAgent"


# ── Resource wire shapes ─────────────────────────────────────────────────


class Category(TypedDict):
    id: str
    code: str
    name: str
    sku_cap: int
    active_sku_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    name: str
    contact_email: str
    quality_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    category_id: str
    sku_code: str
    name: str
    kind: str
    shelf_ready_packaging: bool
    barcode_count: int
    unit_cost_cents: int
    price_cents: int
    primary_supplier_id: Optional[str]
    secondary_supplier_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplierTender(TypedDict):
    id: str
    product_id: str
    bid_ceiling_cents: int
    min_sources: int
    status: str
    winning_primary_bid_id: Optional[str]
    winning_secondary_bid_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TenderBid(TypedDict):
    id: str
    tender_id: str
    supplier_id: str
    unit_cost_cents: int
    award_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class BlindQualityPanel(TypedDict):
    id: str
    bid_id: str
    sample_code: str
    score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict):
    id: str
    code: str
    name: str
    tier: str
    weekly_labor_budget_cents: int
    coins_outstanding: int
    coin_liability_cents: int
    refund_liability_cents: int
    refund_paid_cents: int
    finds_sell_through_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    store_id: str
    name: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FindsBuy(TypedDict):
    id: str
    product_id: str
    week_start_date: str
    week_end_date: str
    total_quantity: int
    allocated_quantity: int
    remaining_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FindsAllocation(TypedDict):
    id: str
    finds_buy_id: str
    store_id: str
    allocated_quantity: int
    sold_quantity: int
    remaining_quantity: int
    sale_start_date: str
    sale_end_date: str
    clearance_markdown_pct: Optional[float]
    clearance_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CartCoinEvent(TypedDict):
    # Append-only ledger entry: id and created_at only, no updated_at, no version.
    id: str
    store_id: str
    event_type: str
    coin_count: int
    created_at: str


class RegisterShift(TypedDict):
    id: str
    store_id: str
    cashier_id: str
    started_at: str
    closed_at: Optional[str]
    items_scanned: int
    voids: int
    provisional_scan_rate: float
    final_scan_rate: Optional[float]
    compliance: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LaborWindow(TypedDict):
    id: str
    store_id: str
    aisle_zone: str
    role: str
    starts_at: str
    ends_at: str
    cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityClaim(TypedDict):
    id: str
    product_id: str
    store_id: str
    quantity: int
    unit_price_cents: int
    purchase_date: str
    reason: str
    refund_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
