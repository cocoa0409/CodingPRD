"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this system carries the common system-managed fields
(``id``, ``created_at``, ``updated_at``, ``version``) -- no resource is
immutable after creation.
"""

from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enumerations ────────────────────────────────────────────────────────────

class FranchiseeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EntityType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    LLC = "LLC"
    CORPORATION = "CORPORATION"


class RiskBand(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class TransferStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class StoreFormat(str, Enum):
    URBAN = "URBAN"
    SUBURBAN = "SUBURBAN"
    RURAL = "RURAL"


class OwnershipParty(str, Enum):
    FRANCHISOR = "FRANCHISOR"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    RENEWED = "RENEWED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class PerformanceTier(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"
    PREMIER = "PREMIER"


class SettlementStatus(str, Enum):
    OPEN = "OPEN"
    DRAW_PAID = "DRAW_PAID"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"


class RevenueCategory(str, Enum):
    MERCHANDISE = "MERCHANDISE"
    FUEL = "FUEL"
    SERVICES = "SERVICES"


class DrawAdvanceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    RECOVERED = "RECOVERED"
    REVERSED = "REVERSED"


class VendorRebateStatus(str, Enum):
    POSTED = "POSTED"
    APPLIED = "APPLIED"
    RETRACTED = "RETRACTED"


class ShrinkAuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COUNTED = "COUNTED"
    FINALIZED = "FINALIZED"


class DeliveryWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"


class DayOfWeek(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class FreshOrderStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    FRANCHISOR_ADMIN = "FranchisorAdmin"
    FRANCHISEE = "Franchisee"
    FIELD_AUDITOR = "FieldAuditor"
    COMMISSARY = "Commissary"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────
# All ten resources declare common_fields: true, so each carries the full set
# of system-managed fields including updated_at and version.

class Franchisee(TypedDict):
    id: str
    legal_name: str
    owner_name: str
    entity_type: str
    stated_net_worth_cents: int
    draw_outstanding_cents: int
    open_shrink_charge_cents: int
    audit_adjusted_net_worth_cents: int
    risk_band: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict):
    id: str
    franchisee_id: str
    store_number: str
    state_code: str
    format: str
    opened_on: str
    lease_owner: str
    equipment_owner: str
    monthly_rent_cents: int
    cold_chain_certified: bool
    status: str
    transfer_status: str
    transfer_target_franchisee_id: Optional[str]
    transfer_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FranchiseAgreement(TypedDict):
    id: str
    franchisee_id: str
    store_id: str
    split_pct: float
    royalty_pct: float
    waste_share_pct: float
    shrink_responsibility_pct: float
    rebate_pass_pct: float
    minimum_net_worth_cents: int
    term_start: str
    term_end: str
    renewal_window_days: int
    performance_tier: str
    renewal_eligibility_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    store_id: str
    franchisee_id: str
    period_start: str
    period_end: str
    trailing_avg_gross_profit_cents: int
    gross_sales_cents: int
    cost_of_goods_cents: int
    rebate_credit_cents: float
    gross_profit_cents: float
    provisional_gross_profit_cents: float
    eligible_split_pct: float
    provisional_split_cents: float
    franchisee_split_cents: float
    franchisor_share_cents: float
    shrink_charge_cents: float
    waste_charge_cents: float
    draw_recovery_cents: float
    net_settlement_cents: float
    provisional: bool
    status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RevenueLine(TypedDict):
    id: str
    settlement_id: str
    category: str
    gross_sales_cents: int
    cost_of_goods_cents: int
    line_gross_profit_cents: int
    created_at: str
    updated_at: str
    version: int


class DrawAdvance(TypedDict):
    id: str
    franchisee_id: str
    store_id: str
    amount_cents: int
    drawn_on: str
    recovered_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorRebate(TypedDict):
    id: str
    store_id: str
    vendor_name: str
    vendor_code: str
    recommended_vendor: bool
    rebate_cents: int
    period_start: str
    period_end: str
    flowthrough_cents: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ShrinkAudit(TypedDict):
    id: str
    store_id: str
    period_start: str
    period_end: str
    book_inventory_cents: int
    physical_inventory_cents: Optional[int]
    shrink_cents: Optional[int]
    shrink_charge_cents: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryWindow(TypedDict):
    id: str
    store_id: str
    commissary_code: str
    day_of_week: str
    window_start: str
    window_end: str
    capacity_units: int
    reserved_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FreshOrder(TypedDict):
    id: str
    store_id: str
    delivery_window_id: str
    sku_code: str
    ordered_units: int
    delivered_units: Optional[int]
    waste_units: Optional[int]
    unit_cost_cents: int
    line_waste_cents: Optional[float]
    waste_share_cents: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "FranchiseeStatus", "EntityType", "RiskBand", "StoreStatus", "TransferStatus",
    "StoreFormat", "OwnershipParty", "AgreementStatus", "PerformanceTier",
    "SettlementStatus", "RevenueCategory", "DrawAdvanceStatus", "VendorRebateStatus",
    "ShrinkAuditStatus", "DeliveryWindowStatus", "DayOfWeek", "FreshOrderStatus",
    "UserRole",
    "Franchisee", "Store", "FranchiseAgreement", "Settlement", "RevenueLine",
    "DrawAdvance", "VendorRebate", "ShrinkAudit", "DeliveryWindow", "FreshOrder",
]