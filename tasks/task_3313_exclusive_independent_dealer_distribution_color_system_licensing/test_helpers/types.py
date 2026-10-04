"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD section 2.4, most resources carry id/created_at/updated_at/version;
RematchTask and DealerChannelEvent carry only id and created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    REGION_MANAGER = "RegionManager"
    CHANNEL_DIRECTOR = "ChannelDirector"
    DEALER_PRINCIPAL = "DealerPrincipal"
    COLOR_LAB_ADMIN = "ColorLabAdmin"
    EQUIPMENT_TECH = "EquipmentTech"


class DealerStatus(str, Enum):
    APPLIED = "APPLIED"
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ChannelPosture(str, Enum):
    INDEPENDENT_ONLY = "INDEPENDENT_ONLY"
    OVERRIDE_REQUIRED = "OVERRIDE_REQUIRED"
    BLOCKED = "BLOCKED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class EquipmentStatus(str, Enum):
    INSTALLED = "INSTALLED"
    CALIBRATED = "CALIBRATED"
    CALIBRATION_OVERDUE = "CALIBRATION_OVERDUE"
    DECOMMISSIONED = "DECOMMISSIONED"


class ColorantSystemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ProductLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ChannelClass(str, Enum):
    DEALER_EXCLUSIVE = "DEALER_EXCLUSIVE"
    SPECIALTY = "SPECIALTY"


class FormulaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class FormulationChangeStatus(str, Enum):
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"
    EFFECTIVE = "EFFECTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RematchTaskStatus(str, Enum):
    PENDING = "PENDING"
    DONE = "DONE"


class LicenseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class FeeBasis(str, Enum):
    FULL = "FULL"
    PRORATED = "PRORATED"


class ContractorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ContractorTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class PurchaseStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class OrderPurpose(str, Enum):
    INITIAL_STOCK = "INITIAL_STOCK"
    RESTOCK = "RESTOCK"


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class Channel(str, Enum):
    INDEPENDENT = "INDEPENDENT"
    BIGBOX = "BIGBOX"


class ChannelEventStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"


class Region(TypedDict, total=False):
    id: str
    code: str
    name: str
    territory_radius_miles: float
    exclusivity_block_threshold_pct: float
    active_dealer_count: int
    pending_application_count: int
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict, total=False):
    id: str
    region_id: str
    legal_name: str
    latitude: float
    longitude: float
    status: str
    channel_posture: str
    bigbox_share_pct: float
    exclusivity_attested_on: str
    branding_compliant: bool
    coop_accrual_rate: float
    coop_balance_cents: int
    coop_pending_cents: int
    annual_net_purchase_cents: int
    inventory_minimum_met: bool
    created_at: str
    updated_at: str
    version: int


class DealerApplication(TypedDict, total=False):
    id: str
    region_id: str
    dealer_id: str
    latitude: float
    longitude: float
    legal_name: str
    distance_to_nearest_miles: Optional[float]
    territory_conflict: bool
    nearest_dealer_id: Optional[str]
    nearest_dealer_notified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict, total=False):
    id: str
    dealer_id: str
    serial_no: str
    model: str
    colorant_system_id: str
    installed_on: str
    last_calibrated_on: Optional[str]
    calibration_due_on: Optional[str]
    consecutive_failed_calibrations: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ColorantSystem(TypedDict, total=False):
    id: str
    code: str
    name: str
    generation: int
    annual_license_fee_cents: int
    min_initial_inventory_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductLine(TypedDict, total=False):
    id: str
    colorant_system_id: str
    code: str
    name: str
    channel_class: str
    base_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ColorFormula(TypedDict, total=False):
    id: str
    product_line_id: str
    code: str
    display_name: str
    formulation_version: int
    effective_from: str
    rematch_pending: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FormulationChange(TypedDict, total=False):
    id: str
    product_line_id: str
    title: str
    reason: str
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RematchTask(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    formulation_change_id: str
    dealer_id: str
    color_formula_id: str
    old_formulation_version: int
    new_formulation_version: int
    status: str
    created_at: str


class ColorLicense(TypedDict, total=False):
    id: str
    dealer_id: str
    colorant_system_id: str
    started_on: str
    expires_on: str
    fee_basis: str
    fee_charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractorAccount(TypedDict, total=False):
    id: str
    dealer_id: str
    company_name: str
    enrolled_on: str
    rolling_net_spend_cents: int
    tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractorPurchase(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    contractor_account_id: str
    product_line_id: str
    units: int
    reward_points_redeemed: int
    unit_price_cents: int
    invoice_cents: int
    reward_points_redemption_cents: int
    refund_cents: int
    tier_at_post: str
    status: str
    created_at: str


class DealerOrder(TypedDict, total=False):
    id: str
    dealer_id: str
    product_line_id: str
    units: int
    purpose: str
    unit_price_cents: int
    invoice_cents: int
    coop_accrued_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CoopClaim(TypedDict, total=False):
    id: str
    dealer_id: str
    amount_cents: int
    description: str
    activity_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DealerChannelEvent(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    dealer_id: str
    period_start: str
    period_end: str
    channel: str
    sales_cents: int
    status: str
    created_at: str
