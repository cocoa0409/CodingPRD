"""Domain types: entity TypedDicts, status enums and the role enum.

Only the shape of the API surface is declared here; the behaviour lives in the PRD.
Entities whose rows are append-only carry only ``id`` and ``created_at``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum ────────────────────────────────────────

class UserRole(str, Enum):
    MERCHANDISER = "Merchandiser"
    VENDOR = "Vendor"
    INVENTORY_PLANNER = "InventoryPlanner"
    CROSS_DOCK_OPERATOR = "CrossDockOperator"
    CUSTOMER_SERVICE = "CustomerService"
    CUSTOMER = "Customer"
    ANY = "Any"


# ─── Status enums ─────────────────────────────────────

class VendorStanding(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class VendorTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIER = "PREMIER"
    STRATEGIC = "STRATEGIC"


class ShopStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EventContributionVariant(str, Enum):
    PROJECTED_WHILE_LIVE = "PROJECTED_WHILE_LIVE"
    REALIZED_ON_CLOSURE = "REALIZED_ON_CLOSURE"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SOLD_OUT = "SOLD_OUT"
    WITHDRAWN = "WITHDRAWN"


class CustomerAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class OrderStatus(str, Enum):
    AGGREGATING = "AGGREGATING"
    AWAITING_VENDOR = "AWAITING_VENDOR"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CROSS_DOCKED = "CROSS_DOCKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class PaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class ConfirmationStatus(str, Enum):
    PENDING_AGGREGATION = "PENDING_AGGREGATION"
    PENDING_VENDOR = "PENDING_VENDOR"
    VENDOR_CONFIRMED = "VENDOR_CONFIRMED"
    PURCHASE_ORDER_ISSUED = "PURCHASE_ORDER_ISSUED"
    IN_TRANSIT_TO_CROSS_DOCK = "IN_TRANSIT_TO_CROSS_DOCK"
    RECEIVED_AT_CROSS_DOCK = "RECEIVED_AT_CROSS_DOCK"
    SHIPPED = "SHIPPED"
    SHORT_SHIPPED = "SHORT_SHIPPED"
    CANCELLED = "CANCELLED"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CLOSED_SHORT = "CLOSED_SHORT"
    CANCELLED = "CANCELLED"


class POLineStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    FILLED = "FILLED"
    CLOSED_SHORT = "CLOSED_SHORT"


class ShipmentStatus(str, Enum):
    REPORTED = "REPORTED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"


class ParcelStatus(str, Enum):
    FORMING = "FORMING"
    SEALED = "SEALED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AI1_APPROVED = "AI1_APPROVED"
    AI1_DENIED = "AI1_DENIED"
    CS_REVIEW = "CS_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RECEIVED = "RECEIVED"
    REFUNDED = "REFUNDED"


class SettlementBasis(str, Enum):
    REFUND = "REFUND"
    STORE_CREDIT = "STORE_CREDIT"
    NONE = "NONE"


class LedgerSourceKind(str, Enum):
    OVERSELL = "OVERSELL"
    SHORT_SHIP = "SHORT_SHIP"
    CANCELLATION = "CANCELLATION"
    RETURN_GOODWILL = "RETURN_GOODWILL"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


class LedgerEntryStatus(str, Enum):
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"


# ─── Entity shapes ────────────────────────────────────

class Vendor(TypedDict):
    id: str
    legal_name: str
    vendor_tier: str
    standing: str
    fill_rate_floor_pct: Optional[float]
    rolling_fill_rate_units_shipped: int
    rolling_fill_rate_units_ordered: int
    standing_evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shop(TypedDict):
    id: str
    vendor_id: str
    shop_name: str
    shop_status: str
    curated_sku_count: int
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    shop_id: str
    event_title: str
    starts_at: str
    ends_at: str
    ship_time_quote_days: int
    event_status: str
    checkpoint_index: int
    units_ordered_total: int
    units_po_committed_total: int
    oversell_units_total: int
    net_contribution_cents: Optional[int]
    net_contribution_variant: Optional[str]
    closed_at: Optional[str]
    open_event_for_shop: bool
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    event_id: str
    vendor_sku: str
    unit_price_cents: int
    vendor_unit_cost_cents: int
    allocation_units: int
    units_ordered: int
    oversell_units: int
    listing_status: str
    reveal_at: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    account_status: str
    store_credit_balance_cents: int
    refund_balance_cents: int
    lifetime_credit_issued_cents: int
    created_at: str
    updated_at: str
    version: int


class CustomerOrder(TypedDict):
    id: str
    customer_id: str
    order_status: str
    payment_status: str
    disclosed_ship_time_days: Optional[int]
    cancellation_window_ends_at: Optional[str]
    cancellation_waived: bool
    order_total_cents: int
    refund_due_cents: int
    parcel_consolidated_at: Optional[str]
    ready_to_ship: bool
    created_at: str
    updated_at: str
    version: int


class Confirmation(TypedDict):
    id: str
    customer_order_id: str
    listing_id: str
    quantity: int
    confirmation_status: str
    confirmed_units: Optional[int]
    short_shipped_units: int
    oversold_units: int
    line_unit_price_cents: Optional[int]
    refund_due_cents: int
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict):
    id: str
    vendor_id: str
    event_id: str
    po_status: str
    quantity_ordered: int
    quantity_shipped: int
    fill_rate_pct: Optional[float]
    fill_rate_floor_pct: Optional[float]
    due_at: Optional[str]
    issued_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class POLine(TypedDict):
    id: str
    purchase_order_id: str
    listing_id: str
    quantity_ordered: int
    quantity_confirmed: int
    quantity_shipped: int
    poline_status: str
    created_at: str
    updated_at: str
    version: int


class VendorShipment(TypedDict):
    id: str
    purchase_order_id: str
    quantity_shipped: int
    carrier_tracking_code: str
    shipped_at: str
    arrived_at: Optional[str]
    shipment_status: str
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    customer_order_id: str
    parcel_status: str
    contained_line_ids: List[str]
    vendor_shipment_count: int
    sealed_at: Optional[str]
    dispatch_eta: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict):
    id: str
    confirmation_id: str
    reason_code: str
    return_status: str
    settlement_basis: Optional[str]
    settlement_amount_cents: Optional[int]
    cs_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditLedger(TypedDict):
    """Append-only: carries ONLY id and created_at — no updated_at, no version."""
    id: str
    customer_id: str
    source_kind: str
    source_ref_id: str
    amount_cents: int
    entry_status: str
    idempotency_key: Optional[str]
    created_at: str