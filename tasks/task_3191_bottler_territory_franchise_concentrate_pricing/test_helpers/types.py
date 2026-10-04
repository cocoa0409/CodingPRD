"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class BrandOwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TerritoryStatus(str, Enum):
    OPEN = "OPEN"
    FRANCHISED = "FRANCHISED"
    REFRANCHISED = "REFRANCHISED"


class BottlerAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    REFRANCHISED = "REFRANCHISED"


class ProductLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CpoFulfillmentStatus(str, Enum):
    PLACED = "PLACED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class CpoPricingStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"


class NcaStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISPUTED = "DISPUTED"
    INACTIVE = "INACTIVE"


class CustomerChannel(str, Enum):
    RETAIL = "RETAIL"
    FOUNTAIN = "FOUNTAIN"


class DsdFulfillmentStatus(str, Enum):
    BOOKED = "BOOKED"
    DELIVERED = "DELIVERED"
    VOIDED = "VOIDED"


class DsdPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"


class EquipmentStatus(str, Enum):
    IN_WAREHOUSE = "IN_WAREHOUSE"
    PLACED = "PLACED"
    UNDER_SERVICE = "UNDER_SERVICE"


class TransferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VALUED = "VALUED"
    NEGOTIATING = "NEGOTIATING"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"


class LaunchStatus(str, Enum):
    PLANNED = "PLANNED"
    CHANGEOVER_SCHEDULED = "CHANGEOVER_SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMMIT_REVIEW = "COMMIT_REVIEW"
    MET = "MET"
    PENALIZED = "PENALIZED"
    EXTENDED = "EXTENDED"


class AccrualBasis(str, Enum):
    CASE_VOLUME = "CASE_VOLUME"
    NET_REVENUE = "NET_REVENUE"


class FundEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    DISBURSEMENT = "DISBURSEMENT"
    CLAWBACK = "CLAWBACK"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BRAND_OWNER_ADMIN = "BrandOwnerAdmin"
    BOTTLER_OPS = "BottlerOps"
    CUSTOMER_MANAGER = "CustomerManager"
    FIELD_TECHNICIAN = "FieldTechnician"


class BrandOwner(TypedDict, total=False):
    id: str
    name: str
    home_country: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Territory(TypedDict, total=False):
    id: str
    brand_owner_id: str
    code: str
    region_label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BottlerAgreement(TypedDict, total=False):
    id: str
    territory_id: str
    bottler_name: str
    concentrate_base_index: float
    marketing_accrual_basis: str
    status: str
    marketing_fund_balance_cents: int
    service_budget_cents: int
    service_spent_cents: int
    margin_ledger_cents: int
    created_at: str
    updated_at: str
    version: int


class ProductLine(TypedDict, total=False):
    id: str
    brand_owner_id: str
    line_code: str
    concentrate_base_price_per_gallon: float
    is_mandatory: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ConcentratePriceIndex(TypedDict, total=False):
    id: str
    brand_owner_id: str
    quarter: str
    index_value: float
    created_at: str


class ConcentratePurchaseOrder(TypedDict, total=False):
    id: str
    agreement_id: str
    product_line_id: str
    quantity_gallons: int
    delivery_quarter: str
    fulfillment_status: str
    pricing_status: str
    provisional_unit_price: float
    provisional_amount_cents: int
    final_unit_price: Optional[float]
    final_amount_cents: Optional[int]
    price_delta_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class NationalCustomerAgreement(TypedDict, total=False):
    id: str
    brand_owner_id: str
    nca_code: str
    national_price_cents: int
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    agreement_id: str
    nca_id: Optional[str]
    name: str
    channel: str
    local_price_cents: int
    bound_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DsdOrderLine(TypedDict, total=False):
    product_line_id: str
    quantity_cases: int
    discount_pct: float


class DsdOrder(TypedDict, total=False):
    id: str
    customer_id: str
    lines: List[DsdOrderLine]
    fulfillment_status: str
    payment_status: str
    invoice_total_cents: int
    created_at: str
    updated_at: str
    version: int


class ColdDrinkEquipment(TypedDict, total=False):
    id: str
    agreement_id: str
    asset_tag: str
    customer_id: Optional[str]
    placed_from: Optional[str]
    placed_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceWindow(TypedDict, total=False):
    id: str
    equipment_id: str
    technician_label: str
    window_start: str
    window_end: str
    cost_cents: int
    created_at: str


class FountainAccount(TypedDict, total=False):
    id: str
    customer_id: str
    syrup_on_hand_gallons: float
    maintenance_overdue: bool
    created_at: str
    updated_at: str
    version: int


class SyrupDelivery(TypedDict, total=False):
    id: str
    fountain_account_id: str
    gallons: float
    delivered_at: str
    created_at: str


class TerritoryTransfer(TypedDict, total=False):
    id: str
    territory_id: str
    buyer_name: str
    reported_ebitda_cents: int
    valuation_cents: Optional[int]
    valuation_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InnovationLaunch(TypedDict, total=False):
    id: str
    agreement_id: str
    product_line_id: str
    committed_cases: int
    launch_start: str
    launch_end: str
    cases_sold: int
    changeover_completed: bool
    penalty_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketingFundEntry(TypedDict, total=False):
    id: str
    agreement_id: str
    entry_type: str
    period: str
    cases_sold: Optional[int]
    net_revenue_cents: Optional[int]
    amount_cents: int
    requested_amount_cents: Optional[int]
    reference_entry_id: Optional[str]
    created_at: str
