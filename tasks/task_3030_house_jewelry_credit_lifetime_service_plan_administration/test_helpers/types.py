"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity surface (§2 and §3). Resources carrying the
common field set expose ``id``/``created_at``/``updated_at``/``version``;
the two immutable event records (payoff ledger entries and repair holds)
carry only ``id`` and ``created_at``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CHAIN_ADMIN = "ChainAdmin"
    STORE_MANAGER = "StoreManager"
    CREDIT_ANALYST = "CreditAnalyst"
    SALES_ASSOCIATE = "SalesAssociate"
    CUSTOMER_SERVICE = "CustomerService"
    CUSTOMER = "Customer"


class StoreStatus(str, Enum):
    OPEN = "OPEN"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AccountStatus(str, Enum):
    NO_FILE = "NO_FILE"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CreditTier(str, Enum):
    NO_FILE = "NO_FILE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class DecisionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    COUNTERED = "COUNTERED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class DecisionKind(str, Enum):
    APPROVE_FULL = "APPROVE_FULL"
    APPROVE_COUNTERED = "APPROVE_COUNTERED"
    DECLINE = "DECLINE"


class PlanCode(str, Enum):
    PROMO_12_6M = "PROMO_12_6M"
    PROMO_18_6M = "PROMO_18_6M"
    PROMO_24_12M = "PROMO_24_12M"


class PlanStatus(str, Enum):
    ACCRUING = "ACCRUING"
    PAID = "PAID"
    CAPITALIZED = "CAPITALIZED"
    DEFAULTED = "DEFAULTED"
    VOIDED = "VOIDED"


class LedgerEntryKind(str, Enum):
    INSTALLMENT = "INSTALLMENT"
    LUMPSUM_PAYOFF = "LUMPSUM_PAYOFF"
    CAPITALIZATION = "CAPITALIZATION"
    TRADE_UP_CREDIT = "TRADE_UP_CREDIT"


class LedgerDirection(str, Enum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"


class ReferenceBucket(str, Enum):
    PROMOTIONAL = "PROMOTIONAL"
    CUSTOM_DESIGN = "CUSTOM_DESIGN"
    RETAIL = "RETAIL"


class CoverageStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    REMINDER_ISSUED = "REMINDER_ISSUED"
    ACTIVE = "ACTIVE"
    GRACE_PERIOD = "GRACE_PERIOD"
    LAPSED = "LAPSED"
    RENEWED = "RENEWED"
    TERMINATED = "TERMINATED"
    VOID = "VOID"


class VisitResult(str, Enum):
    SCHEDULED = "SCHEDULED"
    CLAIMED = "CLAIMED"
    NO_SHOW = "NO_SHOW"


class RepairStatus(str, Enum):
    INTAKE = "INTAKE"
    ROUTED = "ROUTED"
    IN_REPAIR = "IN_REPAIR"
    QC_REVIEW = "QC_REVIEW"
    COMPLETED = "COMPLETED"
    UNREPAIRABLE = "UNREPAIRABLE"
    VERIFIED_LOSS = "VERIFIED_LOSS"
    ABANDONED = "ABANDONED"


class FailureClass(str, Enum):
    STONE_LOSS = "STONE_LOSS"
    SETTING = "SETTING"
    PRONG = "PRONG"
    RESIZE = "RESIZE"
    OTHER = "OTHER"


class CustodyStatus(str, Enum):
    IN_CASE = "IN_CASE"
    IN_VAULT = "IN_VAULT"
    AT_VENDOR = "AT_VENDOR"
    WITHDRAWN = "WITHDRAWN"


class StoneKind(str, Enum):
    NATURAL = "NATURAL"
    LAB_GROWN = "LAB_GROWN"


class PurchaseStatus(str, Enum):
    PENDING = "PENDING"
    FINANCED = "FINANCED"
    COMPLETED = "COMPLETED"
    TRADE_UP_APPLIED = "TRADE_UP_APPLIED"


class DesignStatus(str, Enum):
    DEPOSIT_PAID = "DEPOSIT_PAID"
    CAD_REVISION = "CAD_REVISION"
    CAD_APPROVED = "CAD_APPROVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AppraisalKind(str, Enum):
    INSURANCE = "INSURANCE"
    REPLACEMENT = "REPLACEMENT"


class AppraisalStatus(str, Enum):
    ISSUED = "ISSUED"
    CIRCULATED = "CIRCULATED"
    SUPERSEDED = "SUPERSEDED"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# --- Entity shapes (common field set: id + created_at + updated_at + version) ---


class Store(TypedDict, total=False):
    id: str
    store_code: str
    name: str
    state_code: str
    credit_enabled: bool
    store_status: str
    credit_capacity_cents: int
    store_hold_days: int
    available_credit_capacity_cents: int
    store_absorbed_total_cents: int
    open_repair_liability_cents: int
    open_inspection_count: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    state_code: str
    account_status: str
    credit_tier: str
    standalone_credit_limit_cents: int
    revolving_utilization_bps: int
    lifetime_purchase_cents: int
    outstanding_balance_cents: int
    lost_inspection_streak: int
    created_at: str
    updated_at: str
    version: int


class CreditLimitRegistryState(TypedDict, total=False):
    id: str
    registry_key: str
    credit_tier: str
    base_limit_cents: int
    min_down_payment_pct: float
    min_ticket_cents: int
    all_states_key: str
    registry_type: str
    created_at: str
    updated_at: str
    version: int


class CreditApplication(TypedDict, total=False):
    id: str
    customer_id: str
    store_id: str
    requested_limit_cents: int
    declared_annual_income_cents: Optional[int]
    requested_purchase_amount_cents: int
    down_payment_cents: int
    minimum_down_payment_cents: int
    policy_tier: str
    decision_status: str
    decision_tier: Optional[str]
    approved_limit_cents: int
    min_down_payment_required_cents: int
    down_payment_shortfall_cents: int
    expires_at: str
    decision_rule_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PromotionalPlan(TypedDict, total=False):
    id: str
    customer_id: str
    purchase_id: str
    plan_code: str
    promotional_apr_pct: float
    deferred_months: int
    simplicity_months: int
    deferral_basis_points: int
    installment_amount_cents: int
    installment_quarter_cents: int
    principal_cents: int
    deferred_interest_accrued_cents: int
    final_settlement_amount_cents: int
    merchant_deferral_fee_cents: int
    plan_status: str
    total_paid_cents: int
    simplicity_expires_at: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayoffLedgerEntry(TypedDict, total=False):
    id: str
    plan_id: str
    entry_kind: str
    adjustment_cents: int
    amount_cents: int
    reference_bucket: Optional[str]
    direction: str
    entry_sequence: int
    projected_total_cents: int
    recorded_at: str
    created_at: str


class Diamond(TypedDict, total=False):
    id: str
    stone_code: str
    stone_kind: str
    carat: float
    origin_registry: Optional[str]
    owner_customer_id: Optional[str]
    custody_status: str
    created_at: str
    updated_at: str
    version: int


class ProtectionBundle(TypedDict, total=False):
    id: str
    bundle_code: str
    display_name: str
    bundle_status: str
    lifetime_plan_fee_cents: int
    stone_limit_labor_cents: int
    stone_limit_parts_cents: int
    inspection_interval_days: int
    inspection_cure_days: int
    created_at: str
    updated_at: str
    version: int


class VendorShop(TypedDict, total=False):
    id: str
    shop_code: str
    shop_name: str
    vendor_status: str
    base_turnaround_days: int
    rush_surcharge_cents: int
    open_repair_count: int
    created_at: str
    updated_at: str
    version: int


class ServicePlanRegulation(TypedDict, total=False):
    id: str
    state_code: str
    max_plan_term_months: int
    inspection_required_months: int
    max_inspection_gap_days: int
    lapse_cure_days: int
    replacement_plus_pct: float
    created_at: str
    updated_at: str
    version: int


class ServicePlanRegistration(TypedDict, total=False):
    id: str
    customer_id: str
    purchase_id: str
    diamond_id: str
    store_id: str
    bundle_id: str
    registered_at: str
    coverage_status: str
    inspection_due_at: str
    cure_expires_at: str
    last_inspection_at: Optional[str]
    next_inspection_at: Optional[str]
    missed_inspection_count: int
    plan_term_months: int
    renewal_count: int
    replacement_claims_used: int
    is_valid: bool
    created_at: str
    updated_at: str
    version: int


class InspectionVisit(TypedDict, total=False):
    id: str
    registration_id: str
    store_id: str
    visit_at: str
    result: str
    scheduled_for_at: Optional[str]
    inspection_status: str
    claimed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Repair(TypedDict, total=False):
    id: str
    customer_id: str
    store_id: str
    diamond_id: str
    registration_id: str
    vendor_shop_code: Optional[str]
    failure_class: str
    vendor_is_rush: bool
    declared_parts_cents: int
    declared_labor_cents: int
    accepted_at: str
    promised_delivery_at: Optional[str]
    loss_liability_cents: int
    insurance_parts_cents: int
    customer_parts_cents: int
    customer_labor_cents: int
    reserve_cents: int
    store_absorbed_cents: int
    repair_status: str
    pickup_deadline_at: Optional[str]
    stored_appraisal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairHold(TypedDict, total=False):
    id: str
    repair_id: str
    extended_promised_delivery_at: str
    extension_days: int
    deadline_adjusted: bool
    imposed_breach_adjustment_cents: int
    recorded_at: str
    created_at: str


class Appraisal(TypedDict, total=False):
    id: str
    repair_id: str
    customer_id: str
    appraised_value_cents: int
    traceability_document_url: Optional[str]
    appraisal_kind: str
    insurance_schedule_ref: Optional[str]
    appraisal_status: str
    circulated_at: str
    created_at: str
    updated_at: str
    version: int


class Purchase(TypedDict, total=False):
    id: str
    customer_id: str
    store_id: str
    diamond_id: Optional[str]
    bundle_id: Optional[str]
    base_price_cents: int
    origin_purchase_id: Optional[str]
    trade_up_credit_cents: int
    trade_up_floor_cents: int
    net_amount_cents: int
    protection_fee_cents: int
    purchase_status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustomDesignOrder(TypedDict, total=False):
    id: str
    customer_id: str
    store_id: str
    estimate_amount_cents: int
    deposit_cents: int
    deposit_pct: float
    revision_count: int
    free_revisions_used: int
    revision_fee_cents: int
    design_status: str
    approved_at: Optional[str]
    cancellation_fee_cents: int
    non_refundable_deposit_cents: int
    refundable_deposit_cents: int
    created_at: str
    updated_at: str
    version: int


class BillingStatement(TypedDict, total=False):
    id: str
    customer_id: str
    statement_period: str
    bucket_totals_cents: dict
    min_payment_due_cents: int
    statement_balance_cents: int
    statement_status: str
    created_at: str
    updated_at: str
    version: int


ENTITY_TYPES = {
    "Store": Store,
    "Customer": Customer,
    "CreditApplication": CreditApplication,
    "PromotionalPlan": PromotionalPlan,
    "PayoffLedgerEntry": PayoffLedgerEntry,
    "Diamond": Diamond,
    "ProtectionBundle": ProtectionBundle,
    "VendorShop": VendorShop,
    "ServicePlanRegulation": ServicePlanRegulation,
    "ServicePlanRegistration": ServicePlanRegistration,
    "InspectionVisit": InspectionVisit,
    "Repair": Repair,
    "RepairHold": RepairHold,
    "Appraisal": Appraisal,
    "Purchase": Purchase,
    "CustomDesignOrder": CustomDesignOrder,
    "BillingStatement": BillingStatement,
}

__all__: List[str] = [
    "UserRole",
    "StoreStatus",
    "AccountStatus",
    "CreditTier",
    "DecisionStatus",
    "DecisionKind",
    "PlanCode",
    "PlanStatus",
    "LedgerEntryKind",
    "LedgerDirection",
    "ReferenceBucket",
    "CoverageStatus",
    "VisitResult",
    "RepairStatus",
    "FailureClass",
    "CustodyStatus",
    "StoneKind",
    "PurchaseStatus",
    "DesignStatus",
    "AppraisalKind",
    "AppraisalStatus",
    "StatementStatus",
    "Store",
    "Customer",
    "CreditLimitRegistryState",
    "CreditApplication",
    "PromotionalPlan",
    "PayoffLedgerEntry",
    "Diamond",
    "ProtectionBundle",
    "VendorShop",
    "ServicePlanRegulation",
    "ServicePlanRegistration",
    "InspectionVisit",
    "Repair",
    "RepairHold",
    "Appraisal",
    "Purchase",
    "CustomDesignOrder",
    "BillingStatement",
    "ENTITY_TYPES",
]