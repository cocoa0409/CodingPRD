"""Domain types: entity TypedDicts, status enums, role enum (PRD §1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class ItemLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    DISCONTINUED = "DISCONTINUED"


class POStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class ContainerStatus(str, Enum):
    BOOKED = "BOOKED"
    DEPARTED = "DEPARTED"
    AT_PORT = "AT_PORT"
    CUSTOMS_HOLD = "CUSTOMS_HOLD"
    CLEARED = "CLEARED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    PLANNED = "PLANNED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    BLOCKED = "BLOCKED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class CouponStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"


class SaleStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    RETURNED_PARTIAL = "RETURNED_PARTIAL"
    RETURNED_FULL = "RETURNED_FULL"
    VOID = "VOID"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class RecallSeverity(str, Enum):
    NOTICE = "NOTICE"
    STOP_SALE = "STOP_SALE"
    HAZARD = "HAZARD"


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    PURCHASING_MANAGER = "PurchasingManager"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    INVENTORY_PLANNER = "InventoryPlanner"
    MARKETING_MANAGER = "MarketingManager"
    STORE_CLERK = "StoreClerk"
    WARRANTY_ADJUSTER = "WarrantyAdjuster"
    CUSTOMER = "Customer"


class Item(TypedDict, total=False):
    id: str
    sku: str
    name: str
    brand_tier: str
    origin_country: str
    unit_retail_cents: int
    member_price_cents: int
    floor_margin_pct: float
    lead_time_days: int
    unit_weight_kg: float
    lifecycle_status: str
    open_recall_count: int
    warranty_claim_rate: float
    current_landed_unit_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    po_number: str
    lines: List[Dict[str, Any]]
    estimated_duty_cents: int
    estimated_freight_cents: int
    actual_duty_cents: Optional[int]
    actual_freight_cents: Optional[int]
    provisional_landed_costs: Dict[str, int]
    final_landed_costs: Dict[str, int]
    received_quantities: Dict[str, int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict, total=False):
    id: str
    po_id: str
    container_number: str
    lines: List[Dict[str, Any]]
    unallocated_quantities: Dict[str, int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    store_code: str
    name: str
    format: str
    market_tier: str
    receiving_capacity_units: int
    assortment_item_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class StoreAllocation(TypedDict, total=False):
    id: str
    store_id: str
    container_id: str
    item_id: str
    quantity: int
    eta_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict, total=False):
    id: str
    customer_id: str
    tier: str
    status: str
    started_at: str
    expires_at: str
    return_window_days: int
    settled_savings_cents: int
    optimistic_savings_cents: int
    renewal_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Coupon(TypedDict, total=False):
    id: str
    code: str
    channel: str
    audience: str
    discount_type: str
    discount_value: float
    min_basket_cents: int
    max_discount_cents: Optional[int]
    per_customer_limit: int
    budget_cents: int
    budget_spent_cents: int
    budget_reserved_cents: int
    usage_records: List[Dict[str, Any]]
    window_start: str
    window_end: str
    member_early_start: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict, total=False):
    id: str
    store_id: str
    customer_id: str
    status: str
    applied_coupon_id: Optional[str]
    subtotal_cents: int
    coupon_discount_cents: int
    total_cents: int
    store_credit_applied_cents: int
    completed_at: Optional[str]
    returned_line_quantities: Dict[str, int]
    created_at: str
    updated_at: str
    version: int


class SaleLine(TypedDict, total=False):
    id: str
    sale_id: str
    item_id: str
    quantity: int
    is_warranty_line: bool
    covered_item_id: Optional[str]
    warranty_price_cents: Optional[int]
    unit_price_cents: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    sale_line_id: str
    reason: str
    claim_amount_cents: int
    settled_amount_cents: Optional[int]
    appeal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict, total=False):
    id: str
    item_id: str
    severity: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int
