"""Domain types for the fresh date-code, markdown and shrink API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Every entity except ScanPriceCheck carries the full common
field set (id, created_at, updated_at, version); ScanPriceCheck is append-only
and carries only id and created_at.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    STORE_OPERATIONS_ADMIN = "StoreOperationsAdmin"
    DEPARTMENT_MANAGER = "DepartmentManager"
    FRESH_CLERK = "FreshClerk"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    DONATION_PARTNER = "DonationPartner"


# --------------------------------------------------------------------------
# Shared vocabularies
# --------------------------------------------------------------------------


class DepartmentCode(str, Enum):
    MEAT = "MEAT"
    DELI = "DELI"
    BAKERY = "BAKERY"
    PRODUCE = "PRODUCE"
    SEAFOOD = "SEAFOOD"
    DAIRY = "DAIRY"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LadderStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    BLOCKED = "BLOCKED"


class MarkdownPolicyProfile(str, Enum):
    STANDARD = "STANDARD"
    AGGRESSIVE = "AGGRESSIVE"
    CONSERVATIVE = "CONSERVATIVE"


class ItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class LotStatus(str, Enum):
    FRESH = "FRESH"
    MARKED_DOWN = "MARKED_DOWN"
    DONATION_PENDING = "DONATION_PENDING"
    DONATED = "DONATED"
    WITHDRAWN = "WITHDRAWN"
    DEPLETED = "DEPLETED"


class LabelStatus(str, Enum):
    QUEUED = "QUEUED"
    PRINTED = "PRINTED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class LabelReason(str, Enum):
    LADDER_AUTO = "LADDER_AUTO"
    SELL_THROUGH = "SELL_THROUGH"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    RE_LADDER = "RE_LADDER"


class PricingVariant(str, Enum):
    LADDER_DAYS = "LADDER_DAYS"
    SELL_THROUGH = "SELL_THROUGH"


class ScanOutcome(str, Enum):
    MATCH = "MATCH"
    OVERCHARGE = "OVERCHARGE"
    UNDERCHARGE = "UNDERCHARGE"


class EnforcementAction(str, Enum):
    NONE = "NONE"
    PRICE_CORRECTION = "PRICE_CORRECTION"
    LOT_WITHDRAWN = "LOT_WITHDRAWN"


class LogisticsStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    MISSED = "MISSED"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    RECONCILED = "RECONCILED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    PICKED_UP = "PICKED_UP"
    REJECTED = "REJECTED"


class ShrinkCauseCode(str, Enum):
    SPOILAGE = "SPOILAGE"
    DAMAGE = "DAMAGE"
    SAMPLING = "SAMPLING"
    THEFT = "THEFT"


class ShrinkOrigin(str, Enum):
    MANUAL = "MANUAL"
    WITHDRAWAL_AUTO = "WITHDRAWAL_AUTO"


class ShrinkStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"
    POSTED = "POSTED"


class SweepStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SWEPT = "SWEPT"


class DispositionStatus(str, Enum):
    PENDING = "PENDING"
    ESCALATED = "ESCALATED"
    REMEDIATED = "REMEDIATED"


class AuditSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class FindingRemediation(str, Enum):
    NONE = "NONE"
    WITHDRAWN = "WITHDRAWN"


class RecommendationStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


class RecommendationMethod(str, Enum):
    CHRONOLOGICAL_ACTUAL = "CHRONOLOGICAL_ACTUAL"
    FORWARD_LOOKING_PROJECTED = "FORWARD_LOOKING_PROJECTED"


# --------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------


class Store(TypedDict):
    id: str
    store_number: str
    name: str
    region_code: str
    dock_door_codes: List[str]
    donation_program_enabled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FoodBankPartner(TypedDict):
    id: str
    name: str
    contact_email: str
    service_region_code: str
    accepted_department_codes: List[str]
    cold_chain_certified: bool
    status: str
    pickups_completed_count: int
    units_received_total: int
    created_at: str
    updated_at: str
    version: int


class MarkdownLadderRung(TypedDict):
    days_remaining_max: int
    discount_pct: float
    requires_manager_approval: bool


class MarkdownLadder(TypedDict):
    id: str
    name: str
    department_code: str
    rungs: List[MarkdownLadderRung]
    sell_through_floor_pct: float
    max_total_discount_pct: float
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict):
    id: str
    store_id: str
    markdown_ladder_id: str
    code: str
    shelf_life_days_default: int
    past_date_tolerance_hours: int
    shrink_budget_pct: float
    markdown_policy_profile: str
    compliance_status: str
    markdown_liability_cents: int
    shrink_cost_ratio_pct: float
    sweep_epoch: int
    open_finding_count: int
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict):
    id: str
    department_id: str
    upc: str
    description: str
    base_retail_cents: int
    unit_cost_cents: int
    shelf_life_days: Optional[int]
    donation_eligible: bool
    sampling_allowed: bool
    daily_forecast_units: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DateCodeLot(TypedDict):
    id: str
    item_id: str
    production_date: str
    production_batch_code: Optional[str]
    sell_by_at: str
    quantity_original: int
    quantity_on_hand: int
    units_sold: int
    units_shrunk: int
    units_donated: int
    revenue_cents: int
    markdown_giveback_cents: int
    current_price_cents: int
    current_rung_index: int
    total_discount_pct: float
    expected_sell_through_pct: float
    past_date_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MarkdownLabel(TypedDict):
    id: str
    lot_id: str
    supersedes_label_id: Optional[str]
    rung_index: int
    reason: str
    from_price_cents: int
    to_price_cents: int
    discount_pct: float
    barcode: str
    approved_by_user_id: Optional[str]
    status: str
    printed_at: Optional[str]
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScanPriceCheck(TypedDict):
    """Append-only: the PRD gives this resource no updated_at and no version."""

    id: str
    lot_id: str
    register_lane_code: str
    scanned_price_cents: int
    expected_price_cents: int
    variance_cents: int
    label_barcode_snapshot: Optional[str]
    outcome: str
    enforcement_action: str
    created_at: str


class DonationPickup(TypedDict):
    id: str
    store_id: str
    partner_id: str
    dock_door_code: str
    scheduled_window_start: str
    scheduled_window_end: str
    logistics_status: str
    manifest_status: str
    assignment_count: int
    provisional_value_cents: int
    credit_rate_pct: float
    manifest_credit_cents: int
    units_picked_up_total: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonationLotAssignment(TypedDict):
    id: str
    pickup_id: str
    lot_id: str
    quantity_units: int
    unit_price_cents_snapshot: int
    line_value_cents: int
    line_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShrinkEvent(TypedDict):
    id: str
    lot_id: str
    cause_code: str
    quantity_units: int
    note: Optional[str]
    unit_cost_cents_snapshot: int
    cost_value_cents: int
    retail_value_cents: int
    recorded_by_user_id: str
    verified_by_user_id: Optional[str]
    origin: str
    status: str
    verified_at: Optional[str]
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict):
    id: str
    department_id: str
    window_start_at: str
    window_end_at: str
    sweep_status: str
    disposition_status: str
    severity: str
    past_date_lot_count: int
    past_date_units_total: int
    severity_points_total: int
    swept_at: Optional[str]
    opened_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    id: str
    audit_id: str
    lot_id: str
    hours_past_date: int
    units_on_shelf: int
    severity_multiplier: int
    severity_points: int
    remediation: str
    status: str
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderRecommendation(TypedDict):
    id: str
    item_id: str
    window_start_date: str
    window_end_date: str
    method: str
    received_units: int
    shrink_units: int
    shrink_rate_pct: float
    open_units: int
    recommended_order_units: int
    supersedes_recommendation_id: Optional[str]
    status: str
    issued_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
