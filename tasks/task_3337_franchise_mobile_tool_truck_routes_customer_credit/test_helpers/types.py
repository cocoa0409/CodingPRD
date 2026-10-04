"""Domain types: status enums, role enum and entity TypedDicts.

Every resource in this API carries the four system-managed fields `id`,
`created_at`, `updated_at` and `version` (PRD 2.5), so every entity TypedDict
below declares them.
"""
from enum import Enum
from typing import TypedDict, List, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FRANCHISE_OWNER = "FranchiseOwner"
    FRANCHISE_MANAGER = "FranchiseManager"
    CREDIT_OFFICER = "CreditOfficer"
    ROUTE_SALES_REP = "RouteSalesRep"
    WARRANTY_ADMIN = "WarrantyAdmin"
    TECHNICIAN = "Technician"


class TrainingStatus(str, Enum):
    NOT_ENROLLED = "NOT_ENROLLED"
    ENROLLED = "ENROLLED"
    CERTIFIED = "CERTIFIED"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_SERVICE = "IN_SERVICE"
    SUSPENDED = "SUSPENDED"
    PENDING_TRANSFER = "PENDING_TRANSFER"
    RETIRED = "RETIRED"


class TerritoryDevelopmentStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    IN_DEVELOPMENT = "IN_DEVELOPMENT"
    QUALIFIED = "QUALIFIED"
    SURRENDERED = "SURRENDERED"


class ResaleStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class TerritoryModel(str, Enum):
    FRANCHISEE_ASSUMED = "FRANCHISEE_ASSUMED"
    FRANCHISOR_RECOURSE = "FRANCHISOR_RECOURSE"


class RecourseHolder(str, Enum):
    FRANCHISEE = "FRANCHISEE"
    FRANCHISOR = "FRANCHISOR"


class ShopStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SHOP_CHANGE_PENDING = "SHOP_CHANGE_PENDING"
    TRADE_EXITED = "TRADE_EXITED"


class CreditLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    TERMINATED = "TERMINATED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class DecisionSource(str, Enum):
    FRANCHISOR = "FRANCHISOR"
    FRANCHISEE = "FRANCHISEE"


class AccountKind(str, Enum):
    REVOLVING = "REVOLVING"
    LEASE = "LEASE"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELINQUENT = "DELINQUENT"
    CHARGED_OFF = "CHARGED_OFF"
    CLOSED = "CLOSED"


class ChargeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PaymentStatus(str, Enum):
    BOOKED = "BOOKED"
    COLLECTED = "COLLECTED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"
    REVERSED = "REVERSED"


class CollectionSource(str, Enum):
    TRUCK_COLLECTION = "TRUCK_COLLECTION"
    FRANCHISOR_DRAFT = "FRANCHISOR_DRAFT"
    SETTLEMENT_APPLIED = "SETTLEMENT_APPLIED"


class MixProfile(str, Enum):
    DIAGNOSTIC_WEIGHTED = "DIAGNOSTIC_WEIGHTED"
    TOOL_STORAGE = "TOOL_STORAGE"
    POWER_TOOLS = "POWER_TOOLS"


class ProductCategory(str, Enum):
    DIAGNOSTICS = "DIAGNOSTICS"
    TOOL_STORAGE = "TOOL_STORAGE"
    POWER_TOOLS = "POWER_TOOLS"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class ClaimKind(str, Enum):
    WARRANTY_REPLACEMENT = "WARRANTY_REPLACEMENT"
    CLAIM = "CLAIM"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProductOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    ALLOCATED = "ALLOCATED"
    CANCELLED = "CANCELLED"


class PledgeStatus(str, Enum):
    HELD = "HELD"
    BOUND = "BOUND"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"


class LaunchStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    ALLOCATED = "ALLOCATED"
    LIVE = "LIVE"


class RiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Franchisee(TypedDict):
    id: str
    legal_name: str
    training_status: str
    certified_on: Optional[str]
    total_route_count: int
    active_route_count: int
    credit_ceiling_cents: int
    outstanding_credit_cents: int
    recourse_exposure_cents: int
    franchisee_capital_at_risk_cents: int
    fallback_shop_location_id: Optional[str]
    can_resell_territory: bool
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    route_code: str
    route_tier: str
    zip_codes: List[str]
    visit_weekday: int
    truck_label: str
    inventory_invested_cents: int
    mix_plan: str
    territory_model: str
    territory_points: int
    route_status: str
    territory_development_status: str
    resale_status: str
    in_force_from_week: Optional[str]
    in_force_to_week: Optional[str]
    inventory_at_risk_cents: int
    over_pledge_cents: int
    schedule_anchor_utc: str
    reopening_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ShopLocation(TypedDict):
    id: str
    shop_name: str
    street_line: str
    zip_code: str
    shop_status: str
    active_technician_count: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    current_shop_location_id: Optional[str]
    technician_status: str
    credit_line_limit_cents: int
    credit_line_status: str
    home_route_id: Optional[str]
    last_known_shop_name: Optional[str]
    revolving_used_cents: int
    revolving_available_cents: int
    open_account_count: int
    months_in_trade: int
    employment_verified: bool
    created_at: str
    updated_at: str
    version: int


class CreditApplication(TypedDict):
    id: str
    technician_id: str
    requested_limit_cents: int
    requested_kind: str
    requested_term_months: int
    employment_verified: bool
    months_in_trade: int
    prior_delinquency_count: int
    decision_source: str
    application_status: str
    decision_score: int
    approved_limit_cents: int
    approved_kind: Optional[str]
    approved_term_months: int
    created_at: str
    updated_at: str
    version: int


class CreditAccount(TypedDict):
    id: str
    technician_id: str
    application_id: str
    account_kind: str
    credit_limit_cents: int
    account_status: str
    account_status_changed_at: str
    payment_due_weekday: int
    recourse_holder: str
    is_lease_program: bool
    is_revolving_program: bool
    use_final_basis: bool
    current_balance_cents: int
    principal_balance_cents: int
    accrued_finance_charge_cents: int
    credit_available_cents: int
    next_due_weekday: int
    missed_payment_count: int
    last_payment_week_start: Optional[str]
    installment_due_cents: int
    minimum_payment_due_cents: int
    created_at: str
    updated_at: str
    version: int


class FinanceCharge(TypedDict):
    id: str
    accrual_iso_week: str
    accrual_seq: int
    opening_balance_cents: int
    charge_amount_cents: int
    collection_applied_cents: int
    charge_status: str
    charge_resolved_iso_week: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    amount_cents: int
    collection_source: str
    expected_week_start: str
    effective_iso_week: Optional[str]
    payment_status: str
    charge_applied_cents: int
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    technician_id: str
    credit_account_id: str
    mix_profile: str
    order_status: str
    lines: List[dict]
    sale_iso_week: str
    line_count: int
    gross_total_cents: int
    financed_principal_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    line_index: int
    claim_kind: str
    claim_status: str
    idempotency_key: str
    apply_to_account_id: Optional[str]
    filed_iso_week: str
    resolved_iso_week: Optional[str]
    replacement_charge_cents: int
    warranty_credit_amount_cents: int
    principal_allocated_cents: int
    is_idempotent_replay: bool
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    product_name: str
    category: str
    unit_cost_cents: int
    retail_price_cents: int
    default_warranty_months: int
    is_new_launch: bool
    launch_iso_week: Optional[str]
    launch_status: str
    created_at: str
    updated_at: str
    version: int


class InventoryPosition(TypedDict):
    id: str
    product_id: str
    unit_cost_cents: int
    on_hand_qty: int
    reserved_qty: int
    remaining_qty: int
    created_at: str
    updated_at: str
    version: int


class ProductOrder(TypedDict):
    id: str
    product_order_status: str
    mix_profile: str
    investment_ceiling_cents: int
    requested_lines: List[dict]
    requested_cost_cents: int
    ordered_lines: List[dict]
    deferred_lines: List[dict]
    ordered_cost_cents: int
    is_fully_covered: bool
    created_at: str
    updated_at: str
    version: int


class SharePledge(TypedDict):
    id: str
    credit_account_id: str
    pledged_lines: List[dict]
    pledge_status: str
    sustained_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class LaunchAllocation(TypedDict):
    id: str
    product_id: str
    allocation_status: str
    priority_score: float
    review_flag: bool
    allocated_qty: int
    allocated_amount_cents: int
    launch_risk_band: str
    created_at: str
    updated_at: str
    version: int
