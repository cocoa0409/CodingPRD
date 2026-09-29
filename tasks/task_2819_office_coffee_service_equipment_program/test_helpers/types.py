"""Domain types for the office coffee service equipment program API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    """The five roles. Spelling is exact and case-sensitive."""

    PROGRAM_ADMIN = "ProgramAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    BILLING_SPECIALIST = "BillingSpecialist"
    ROUTE_TECHNICIAN = "RouteTechnician"
    CUSTOMER_CONTACT = "CustomerContact"


class ProgramPosture(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"
    CANCELLATION_PENDING = "CANCELLATION_PENDING"
    CLOSED = "CLOSED"


class BillingMode(str, Enum):
    CONSOLIDATED = "CONSOLIDATED"
    PER_SITE = "PER_SITE"


class ServicePosture(str, Enum):
    ACTIVE = "ACTIVE"
    ESCALATED = "ESCALATED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ConsumptionModel(str, Enum):
    HEADCOUNT_MODEL = "HEADCOUNT_MODEL"
    TRAILING_USAGE = "TRAILING_USAGE"


class BrewStyle(str, Enum):
    DRIP = "DRIP"
    SINGLE_CUP = "SINGLE_CUP"
    ESPRESSO = "ESPRESSO"


class ServiceDay(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"


class BrewerClass(str, Enum):
    AIRPOT = "AIRPOT"
    THERMAL = "THERMAL"
    SINGLE_CUP = "SINGLE_CUP"
    ESPRESSO = "ESPRESSO"


class ProductCategory(str, Enum):
    COFFEE = "COFFEE"
    CREAMER = "CREAMER"
    TEA = "TEA"
    WATER = "WATER"
    PANTRY = "PANTRY"


class AssetRole(str, Enum):
    PLACEMENT = "PLACEMENT"
    LOANER = "LOANER"


class AssetStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    PLACED = "PLACED"
    ON_LOAN = "ON_LOAN"
    RECONDITIONING = "RECONDITIONING"
    UNRETURNED = "UNRETURNED"
    RETIRED = "RETIRED"


class ParSource(str, Enum):
    FORECAST = "FORECAST"
    MANUAL = "MANUAL"


class StockStatus(str, Enum):
    STOCKOUT = "STOCKOUT"
    LOW = "LOW"
    IN_STOCK = "IN_STOCK"


class TermsType(str, Enum):
    LOAN = "LOAN"
    RENTAL = "RENTAL"


class PlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETRIEVAL_SCHEDULED = "RETRIEVAL_SCHEDULED"
    RETRIEVED = "RETRIEVED"
    UNRETURNED_BILLED = "UNRETURNED_BILLED"
    SUPERSEDED = "SUPERSEDED"


class ComplianceStatus(str, Enum):
    MEETING_MINIMUM = "MEETING_MINIMUM"
    SHORTFALL_WARNED = "SHORTFALL_WARNED"
    SHORTFALL_BILLED = "SHORTFALL_BILLED"


class AssetCondition(str, Enum):
    SERVICEABLE = "SERVICEABLE"
    UNSERVICEABLE = "UNSERVICEABLE"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class WorkOrderType(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    DESCALE = "DESCALE"
    REPAIR = "REPAIR"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_PARTS = "AWAITING_PARTS"
    RESOLVED = "RESOLVED"


class LoanerStatus(str, Enum):
    NONE = "NONE"
    OUT = "OUT"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"
    WRITTEN_OFF = "WRITTEN_OFF"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_CREDITED = "PARTIALLY_CREDITED"
    FULLY_CREDITED = "FULLY_CREDITED"
    VOID = "VOID"


class LineType(str, Enum):
    PRODUCT = "PRODUCT"
    RENT = "RENT"
    SHORTFALL = "SHORTFALL"
    UNRETURNED_ASSET = "UNRETURNED_ASSET"
    ALLIED_DISCOUNT = "ALLIED_DISCOUNT"
    FREIGHT = "FREIGHT"
    CREDIT = "CREDIT"


class AdjustmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    DEFERRED = "DEFERRED"


class Disposition(str, Enum):
    ACCEPT = "ACCEPT"
    DISPUTE = "DISPUTE"


# --- Entity shapes -----------------------------------------------------------
# Eleven resource types carry id + created_at + updated_at + version.
# EquipmentModel and ProductItem are immutable catalog records and carry
# ONLY id and created_at.


class Account(TypedDict):
    id: str
    legal_name: str
    billing_mode: str
    green_index_baseline_micros: int
    price_protection_days: int
    program_posture: str
    green_price_factor_bps: int
    receivable_balance_cents: int
    escalated_site_count: int
    allied_attachment_bps: int
    price_protection_until: Optional[str]
    cancel_reason: Optional[str]
    retrieval_due_by: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    account_id: str
    route_id: str
    site_name: str
    headcount: int
    days_per_week: int
    consumption_model: str
    service_minutes_estimate: int
    service_posture: str
    escalation_score: float
    forecast_cups_per_week: int
    required_peak_cups_per_hour: int
    consecutive_shortfall_visit_count: int
    recommended_model_id: Optional[str]
    brew_style: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    name: str
    service_day: str
    capacity_minutes: int
    travel_buffer_minutes: int
    booked_minutes_total: int
    created_at: str
    updated_at: str
    version: int


class EquipmentModel(TypedDict):
    """Immutable catalog record: only id and created_at beyond its own fields."""

    id: str
    model_code: str
    brewer_class: str
    cups_per_hour_capacity: int
    min_headcount: int
    max_headcount: int
    monthly_rent_cents: int
    descale_interval_days: int
    list_value_cents: int
    created_at: str


class ProductItem(TypedDict):
    """Immutable catalog record: only id and created_at beyond its own fields."""

    id: str
    sku: str
    category: str
    base_unit_price_micros: int
    pack_units: int
    green_coffee_linked: bool
    created_at: str


class EquipmentAsset(TypedDict):
    id: str
    model_id: str
    serial_number: str
    asset_role: str
    asset_status: str
    reconditioning_until: Optional[str]
    last_descale_at: str
    created_at: str
    updated_at: str
    version: int


class ParLevel(TypedDict):
    id: str
    site_id: str
    product_id: str
    source: str
    par_units: int
    reorder_point_units: int
    on_hand_units: int
    cumulative_delivered_units: int
    cumulative_consumed_units: int
    last_service_at: str
    stock_status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentPlacement(TypedDict):
    id: str
    site_id: str
    asset_id: str
    terms_type: str
    minimum_purchase_cents: int
    min_term_months: int
    placed_at: str
    placement_status: str
    compliance_status: str
    trailing_purchase_cents: int
    shortfall_fee_cents: int
    rent_charge_cents: int
    unreturned_billed_cents: int
    retrieval_due_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceVisitLine(TypedDict):
    product_id: str
    requested_units: int
    delivered_units: Optional[int]
    consumed_units: Optional[int]
    effective_unit_price_micros: Optional[int]
    resulting_on_hand_units: Optional[int]


class ServiceVisit(TypedDict):
    id: str
    site_id: str
    route_id: str
    window_start: str
    window_end: str
    planned_minutes: int
    visit_status: str
    lines: List[ServiceVisitLine]
    shortfall_flag: bool
    completed_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceWorkOrder(TypedDict):
    id: str
    asset_id: str
    site_id: str
    wo_type: str
    wo_status: str
    loaner_status: str
    awaiting_parts_cycles: int
    parts_eta: Optional[str]
    resolution_note: Optional[str]
    loaner_asset_id: Optional[str]
    loaner_out_date: Optional[str]
    loaner_due_back_date: Optional[str]
    loaner_returned_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsolidatedInvoice(TypedDict):
    id: str
    account_id: str
    site_id: Optional[str]
    period_start: str
    period_end: str
    invoice_status: str
    pre_freight_total_cents: int
    allied_discount_bps: int
    allied_discount_cents: int
    freight_cents: int
    total_cents: int
    line_count: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    id: str
    invoice_id: str
    site_id: Optional[str]
    line_type: str
    product_id: Optional[str]
    qty_units: int
    unit_price_micros: int
    amount_cents: int
    credits_applied_cents: int
    target_line_id: Optional[str]
    credit_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceAdjustment(TypedDict):
    id: str
    account_id: str
    effective_at: str
    index_baseline_micros: int
    index_current_micros: int
    movement_bps: int
    adjustment_pct_bps: int
    adj_status: str
    revision_count: int
    dispute_reason: Optional[str]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
