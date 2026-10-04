"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class Region(str, Enum):
    WEST = "WEST"
    CENTRAL = "CENTRAL"
    EAST = "EAST"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AssociateRoleKind(str, Enum):
    SALES = "SALES"
    APPRAISER = "APPRAISER"
    INSPECTOR = "INSPECTOR"
    FINANCE = "FINANCE"
    MANAGER = "MANAGER"


class AssociateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class VehicleLifecycleStatus(str, Enum):
    INTAKE = "INTAKE"
    APPRAISED = "APPRAISED"
    IN_INSPECTION = "IN_INSPECTION"
    RECON = "RECON"
    RETAIL_LISTED = "RETAIL_LISTED"
    SOLD = "SOLD"
    RETURNED = "RETURNED"
    WHOLESALE_PENDING = "WHOLESALE_PENDING"
    AT_AUCTION = "AT_AUCTION"
    DISPOSED = "DISPOSED"


class VehicleHoldStatus(str, Enum):
    NONE = "NONE"
    TRANSFER_HOLD = "TRANSFER_HOLD"
    RETURN_REVIEW_HOLD = "RETURN_REVIEW_HOLD"


class ConditionGrade(str, Enum):
    UNGRADED = "UNGRADED"
    A = "A"
    B = "B"
    C = "C"
    WHOLESALE_ONLY = "WHOLESALE_ONLY"


class AppraisalStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    ACTIVE = "ACTIVE"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class InspectionStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InspectionDisposition(str, Enum):
    UNDECIDED = "UNDECIDED"
    RETAIL = "RETAIL"
    WHOLESALE = "WHOLESALE"


class RepairCategory(str, Enum):
    MECHANICAL = "MECHANICAL"
    BODY = "BODY"
    COSMETIC = "COSMETIC"
    SAFETY = "SAFETY"


class LineStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PricingTriggerKind(str, Enum):
    INITIAL_LISTING = "INITIAL_LISTING"
    SCHEDULED_MARKDOWN = "SCHEDULED_MARKDOWN"
    REPRICING_RUN = "REPRICING_RUN"


class TransferRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FEE_PAID = "FEE_PAID"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    FULFILLED = "FULFILLED"
    HOLD_EXPIRED = "HOLD_EXPIRED"
    CANCELLED = "CANCELLED"


class SaleStatus(str, Enum):
    PENDING_FINANCE = "PENDING_FINANCE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class FinancingApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    OFFERS_PRESENTED = "OFFERS_PRESENTED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class ApprovalTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    DECLINED = "DECLINED"


class LenderCode(str, Enum):
    LENDER_A = "LENDER_A"
    LENDER_B = "LENDER_B"
    LENDER_C = "LENDER_C"


class OfferStatus(str, Enum):
    PRESENTED = "PRESENTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class ReturnReasonCode(str, Enum):
    CHANGED_MIND = "CHANGED_MIND"
    MECHANICAL_DEFECT = "MECHANICAL_DEFECT"
    MISREPRESENTATION = "MISREPRESENTATION"


class ReturnRequestStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class AuctionLotStatus(str, Enum):
    LISTED = "LISTED"
    SOLD = "SOLD"
    UNSOLD = "UNSOLD"


class LedgerEntryKind(str, Enum):
    SALE_REVENUE = "SALE_REVENUE"
    TRADE_IN_PAYABLE = "TRADE_IN_PAYABLE"
    TRANSFER_FEE = "TRANSFER_FEE"
    TRANSFER_FEE_REFUND = "TRANSFER_FEE_REFUND"
    COMMISSION_ACCRUAL = "COMMISSION_ACCRUAL"
    COMMISSION_CLAWBACK = "COMMISSION_CLAWBACK"
    REFUND_PAYABLE = "REFUND_PAYABLE"
    LENDER_REVERSAL = "LENDER_REVERSAL"
    AUCTION_PROCEEDS = "AUCTION_PROCEEDS"


class UserRole(str, Enum):
    PlatformAdmin = "PlatformAdmin"
    StoreManager = "StoreManager"
    Appraiser = "Appraiser"
    ReconditioningInspector = "ReconditioningInspector"
    SalesAssociate = "SalesAssociate"
    FinanceManager = "FinanceManager"
    AuctionManager = "AuctionManager"
    Customer = "Customer"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Primary resources carry id + created_at + updated_at +
# version. Append-only records (RepairLineItem, PricingEvent, LedgerEntry,
# LenderOffer) carry only id + created_at.
# ---------------------------------------------------------------------------


class Store(TypedDict, total=False):
    id: str
    store_code: str
    display_name: str
    region: str
    retail_threshold_pct: float
    transfer_hold_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerAccount(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    credit_score: int
    stated_annual_income_cents: int
    created_at: str
    updated_at: str
    version: int


class Associate(TypedDict, total=False):
    id: str
    display_name: str
    store_id: str
    role_kind: str
    flat_commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    vin: str
    make: str
    model: str
    model_year: int
    odometer_miles: int
    book_value_cents: int
    current_store_id: str
    lifecycle_status: str
    hold_status: str
    condition_grade: str
    current_list_price_cents: Optional[int]
    inventory_acquired_at: str
    days_in_inventory: int
    recon_cost_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict, total=False):
    id: str
    vehicle_id: str
    customer_id: str
    appraiser_id: str
    provisional_offer_cents: int
    final_offer_cents: Optional[int]
    valid_from: Optional[str]
    valid_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReconditioningInspection(TypedDict, total=False):
    id: str
    vehicle_id: str
    inspector_id: str
    opened_at: str
    estimated_repair_total_cents: int
    disposition: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairLineItem(TypedDict, total=False):
    id: str
    inspection_id: str
    category: str
    cost_cents: int
    line_status: str
    created_at: str


class PricingEvent(TypedDict, total=False):
    id: str
    vehicle_id: str
    trigger_kind: str
    old_price_cents: Optional[int]
    new_price_cents: int
    days_in_inventory_at_event: int
    created_at: str


class TransferRequest(TypedDict, total=False):
    id: str
    vehicle_id: str
    customer_id: str
    from_store_id: str
    to_store_id: str
    expedited: bool
    shipping_fee_cents: int
    hold_expires_at: Optional[str]
    supersedes_request_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict, total=False):
    id: str
    vehicle_id: str
    customer_id: str
    associate_id: str
    store_id: str
    trade_in_appraisal_id: Optional[str]
    sale_price_cents: int
    trade_in_credit_cents: int
    amount_due_cents: int
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict, total=False):
    id: str
    sale_id: str
    customer_id: str
    requested_amount_cents: int
    approval_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LenderOffer(TypedDict, total=False):
    id: str
    application_id: str
    lender_code: str
    apr_bps: int
    max_amount_cents: int
    offer_status: str
    created_at: str


class ReturnRequest(TypedDict, total=False):
    id: str
    sale_id: str
    reason_code: str
    opened_at: str
    odometer_at_return: int
    refund_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuctionLot(TypedDict, total=False):
    id: str
    vehicle_id: str
    reserve_price_cents: int
    hammer_price_cents: Optional[int]
    auction_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    id: str
    entry_kind: str
    amount_cents: int
    ref_entity: str
    ref_id: str
    store_id: str
    created_at: str
