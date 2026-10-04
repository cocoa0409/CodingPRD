"""Domain types: status enums, entity TypedDicts, and the role enum.

Entities with the full common-field set carry ``id``, ``created_at``,
``updated_at`` and ``version``. The append-only resources (category scopes,
clean-room queries, audit events) carry only ``id`` and ``created_at`` - their
TypedDicts deliberately omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ── Role vocabulary ──────────────────────────────────────────────────────────

class UserRole(str, Enum):
    RETAILER_ADMIN = "RetailerAdmin"
    CATEGORY_MANAGER = "CategoryManager"
    INSIGHTS_SCIENTIST = "InsightsScientist"
    SUPPLIER_ANALYST = "SupplierAnalyst"
    DATA_STEWARD = "DataSteward"


# ── Status vocabularies ──────────────────────────────────────────────────────

class SupplierAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OFFBOARDED = "OFFBOARDED"


class ContractTier(str, Enum):
    TIER_CATEGORY = "TIER_CATEGORY"
    TIER_BRAND = "TIER_BRAND"
    TIER_PORTFOLIO = "TIER_PORTFOLIO"


class SubscriptionContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ReportType(str, Enum):
    CATEGORY = "CATEGORY"
    BRAND_OWN = "BRAND_OWN"
    COMPETITOR_BLIND = "COMPETITOR_BLIND"


class InsightReportStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GENERATING = "GENERATING"
    READY = "READY"
    SUPPRESSED = "SUPPRESSED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class RedistributionClass(str, Enum):
    SHAREABLE_AGGREGATE = "SHAREABLE_AGGREGATE"
    INTERNAL_ONLY = "INTERNAL_ONLY"
    MODELED_DERIVED = "MODELED_DERIVED"


class AudienceSegmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ActivationChannel(str, Enum):
    COUPON = "COUPON"
    RETAIL_MEDIA = "RETAIL_MEDIA"


class SegmentActivationStatus(str, Enum):
    PENDING = "PENDING"
    LAUNCHED = "LAUNCHED"
    HALTED = "HALTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class IncrementalityStudyStatus(str, Enum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    ANALYSIS = "ANALYSIS"
    IN_REVIEW = "IN_REVIEW"
    PUBLISHED = "PUBLISHED"


class CleanRoomGrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class CleanRoomQueryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    EXECUTED = "EXECUTED"
    SUPPRESSED = "SUPPRESSED"
    REJECTED = "REJECTED"


class LineReviewCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"


class ReviewDeliverableStatus(str, Enum):
    PLANNED = "PLANNED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    MISSED = "MISSED"


class ForecastVariant(str, Enum):
    SIMPLE_AVERAGE = "SIMPLE_AVERAGE"
    SIMILARITY_WEIGHTED = "SIMILARITY_WEIGHTED"


class NewItemForecastStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class AuditEventType(str, Enum):
    REPORT_EXPORTED = "REPORT_EXPORTED"
    QUERY_EXECUTED = "QUERY_EXECUTED"
    QUERY_SUPPRESSED = "QUERY_SUPPRESSED"
    GRANT_APPROVED = "GRANT_APPROVED"
    GRANT_DENIED = "GRANT_DENIED"
    GRANT_REVOKED = "GRANT_REVOKED"
    ACTIVATION_LAUNCHED = "ACTIVATION_LAUNCHED"


# ── Entity TypedDicts (full common-field set) ────────────────────────────────

class SupplierAccount(TypedDict, total=False):
    id: str
    account_name: str
    region: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionContract(TypedDict, total=False):
    id: str
    supplier_account_id: str
    tier: str
    status: str
    report_credit_allowance: int
    report_credits_reserved: int
    report_credits_consumed: int
    report_credits_available: int
    activation_budget_cents: int
    activation_budget_spent_cents: int
    compliance_score: int
    redistribution_allowed: bool
    modeled_derivation_allowed: bool
    created_at: str
    updated_at: str
    version: int


class InsightReport(TypedDict, total=False):
    id: str
    contract_id: str
    report_type: str
    category_code: str
    period_start: str
    period_end: str
    status: str
    credit_cost: int
    household_count: Optional[int]
    own_brand_households: Optional[int]
    other_supplier_aggregate_households: Optional[int]
    redistribution_class: str
    created_at: str
    updated_at: str
    version: int


class AudienceSegment(TypedDict, total=False):
    id: str
    contract_id: str
    segment_name: str
    category_code: str
    min_frequency: Optional[int]
    min_monetary_cents: Optional[int]
    region: Optional[str]
    size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SegmentActivation(TypedDict, total=False):
    id: str
    segment_id: str
    channels: List[str]
    channel_lines: List[Dict[str, Any]]
    total_fee_cents: int
    status: str
    launched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncrementalityStudy(TypedDict, total=False):
    id: str
    brand_code: str
    category_code: str
    window_start: str
    window_end: str
    status: str
    matched_pairs: List[Dict[str, str]]
    test_avg_spend_cents: Optional[float]
    control_avg_spend_cents: Optional[float]
    provisional_lift_pct: Optional[float]
    final_lift_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CleanRoomGrant(TypedDict, total=False):
    id: str
    supplier_account_id: str
    requested_by_user_id: str
    valid_from: str
    valid_until: str
    query_budget_total: int
    query_budget_consumed: int
    query_budget_remaining: int
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LineReviewCycle(TypedDict, total=False):
    id: str
    category_code: str
    window_start: str
    window_end: str
    open_at: str
    planned_open_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewDeliverable(TypedDict, total=False):
    id: str
    cycle_id: str
    contract_id: str
    insight_report_id: str
    due_at: str
    is_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class NewItemForecast(TypedDict, total=False):
    id: str
    contract_id: str
    product_ref: str
    analogs: List[Dict[str, Any]]
    variant: str
    forecast_simple_avg_units: float
    forecast_weighted_units: float
    forecast_selected_units: float
    status: str
    created_at: str
    updated_at: str
    version: int


# ── Append-only entities (id + created_at only) ─────────────────────────────

class CategoryScope(TypedDict, total=False):
    id: str
    contract_id: str
    category_code: str
    brand_codes: List[str]
    created_at: str


class CleanRoomQuery(TypedDict, total=False):
    id: str
    grant_id: str
    dataset_joins: List[str]
    estimated_rows: int
    query_cost: int
    result_rows: int
    status: str
    created_at: str


class AuditEvent(TypedDict, total=False):
    id: str
    event_type: str
    actor_role: str
    actor_user_id: str
    subject_type: str
    subject_id: str
    detail: str
    created_at: str


class PanelHousehold(TypedDict, total=False):
    id: str
    household_ref: str
    region: str
    category_codes: List[str]
    recency_days: int
    frequency_12m: int
    monetary_12m_cents: int
    exposed_brands: List[str]
    brand_metrics: List[Dict[str, Any]]
    created_at: str
