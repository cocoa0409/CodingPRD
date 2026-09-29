"""Domain types for the Catalog Circulation Planning API.

Entity TypedDicts, status enums, and the operator role enum. Every monetary
figure is an integer number of cents, every rate is an integer number of basis
points, and every timestamp is an ISO 8601 UTC string.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CIRCULATION_PLANNER = "CirculationPlanner"
    CIRCULATION_DIRECTOR = "CirculationDirector"
    LIST_BROKER = "ListBroker"
    MARKETING_ANALYST = "MarketingAnalyst"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class SegmentTier(str, Enum):
    BEST = "BEST"
    CORE = "CORE"
    OCCASIONAL = "OCCASIONAL"
    LAPSED = "LAPSED"
    DORMANT = "DORMANT"


class ContactStrategy(str, Enum):
    PREMIUM_FULL = "PREMIUM_FULL"
    STANDARD = "STANDARD"
    REACTIVATION = "REACTIVATION"
    SUPPRESS_ONLY = "SUPPRESS_ONLY"


class RentalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    MODELED = "MODELED"
    ORDERED = "ORDERED"
    DELIVERED = "DELIVERED"
    NETTED = "NETTED"
    CANCELLED = "CANCELLED"


class MergePurgeRunStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    COSTED = "COSTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class DropProductionStatus(str, Enum):
    PLANNED = "PLANNED"
    PRESORTED = "PRESORTED"
    MAILED = "MAILED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DropMeasurementStatus(str, Enum):
    PENDING = "PENDING"
    MATCHBACK_OPEN = "MATCHBACK_OPEN"
    MATCHBACK_CLOSED = "MATCHBACK_CLOSED"


class CostBasis(str, Enum):
    ESTIMATED_POSTAGE = "ESTIMATED_POSTAGE"
    PRESORTED_ACTUAL = "PRESORTED_ACTUAL"


class LineStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ALLOCATED = "ALLOCATED"
    SUPPRESSED = "SUPPRESSED"
    VOIDED = "VOIDED"


class AudienceType(str, Enum):
    HOUSEFILE = "HOUSEFILE"
    RENTAL = "RENTAL"


class PlacementPosition(str, Enum):
    FRONT_COVER = "FRONT_COVER"
    HOT_SPOT = "HOT_SPOT"
    INSIDE = "INSIDE"
    BACK_COVER = "BACK_COVER"


class PresortTier(str, Enum):
    FIVE_DIGIT = "FIVE_DIGIT"
    THREE_DIGIT = "THREE_DIGIT"
    AADC = "AADC"
    MIXED_AADC = "MIXED_AADC"


class ContactChannel(str, Enum):
    MAIL = "MAIL"
    EMAIL = "EMAIL"
    DIGITAL = "DIGITAL"


class ChannelScope(str, Enum):
    MAIL = "MAIL"
    EMAIL = "EMAIL"
    DIGITAL = "DIGITAL"
    ALL = "ALL"


class ContactSource(str, Enum):
    DROP_MAIL_CASCADE = "DROP_MAIL_CASCADE"
    MANUAL_LOG = "MANUAL_LOG"


class TestCellType(str, Enum):
    SEGMENT = "SEGMENT"
    FORMAT = "FORMAT"
    OFFER = "OFFER"


class TestCellRole(str, Enum):
    TEST = "TEST"
    CONTROL = "CONTROL"
    HOLDOUT = "HOLDOUT"


class TestCellStatus(str, Enum):
    PLANNED = "PLANNED"
    MEASURED = "MEASURED"


class TestCellSignificance(str, Enum):
    UNMEASURED = "UNMEASURED"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    INSUFFICIENT_CONTROL = "INSUFFICIENT_CONTROL"
    SIGNIFICANT = "SIGNIFICANT"
    NOT_SIGNIFICANT = "NOT_SIGNIFICANT"


class MatchbackRunStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class AttributionVariant(str, Enum):
    LAST_TOUCH_MAIL = "LAST_TOUCH_MAIL"
    FRACTIONAL_MULTI_TOUCH = "FRACTIONAL_MULTI_TOUCH"


# --------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version
# --------------------------------------------------------------------------
class CatalogSeason(TypedDict):
    id: str
    season_code: str
    fiscal_year: int
    print_cost_per_page_per_thousand_cents: int
    paper_cost_per_lb_cents: int
    paper_oz_per_page_milli: int
    usable_sq_in_per_page: int
    default_postage_estimate_cents_per_piece: int
    cogs_rate_bps: int
    prospect_base_response_bps: int
    prospect_avg_order_value_cents: int
    min_inhome_gap_days: int
    fatigue_window_days: int
    fatigue_suppression_threshold: int
    created_at: str
    updated_at: str
    version: int


class HousefileSegment(TypedDict):
    id: str
    season_id: str
    parent_segment_id: Optional[str]
    segment_code: str
    recency_days: int
    orders_12mo: int
    ltv_cents: int
    housefile_count: int
    avg_order_value_cents: int
    historical_response_rate_bps: int
    rfm_score: int
    segment_tier: str
    contact_strategy: str
    rollup_housefile_count: int
    is_leaf: bool
    fatigue_score: int
    suppressed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProspectListRental(TypedDict):
    id: str
    season_id: str
    list_source_name: str
    requested_gross_names: int
    cost_per_thousand_cents: int
    housefile_overlap_bps: int
    inter_list_overlap_bps: int
    coop_model_score: int
    expected_response_rate_bps: int
    gross_names: int
    net_names_delivered: int
    unit_cost_cents_per_name: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MergePurgeRun(TypedDict):
    id: str
    circulation_plan_id: str
    input_rental_ids: List[str]
    observed_plan_version: int
    processing_order: List[str]
    housefile_leaf_segment_count: int
    gross_input_names: int
    suppressed_names: int
    duplicates_removed: int
    net_mailable_names: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CirculationPlan(TypedDict):
    id: str
    season_id: str
    plan_code: str
    budget_cents: int
    status: str
    revision_round: int
    costed_by_user_id: Optional[str]
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    committed_cost_cents: int
    uncommitted_budget_cents: int
    planned_cost_cents: int
    planned_demand_cents: int
    planned_contribution_cents: int
    created_at: str
    updated_at: str
    version: int


class Drop(TypedDict):
    id: str
    circulation_plan_id: str
    drop_number: int
    in_home_date: str
    page_count: int
    square_inch_capacity: int
    allocated_square_inches: int
    unallocated_square_inches: int
    requested_quantity_total: int
    planned_quantity: int
    weight_oz_milli: int
    print_rebate_bps: int
    printing_cents_per_book: int
    paper_cents_per_book: int
    postage_cents_per_book: int
    cost_per_book_cents: int
    cost_basis: str
    provisional_cost_per_book_cents: int
    postage_total_cents: int
    automation_share_bps: int
    automation_qualified: bool
    production_status: str
    measurement_status: str
    mailed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CirculationLine(TypedDict):
    id: str
    drop_id: str
    housefile_segment_id: Optional[str]
    prospect_list_rental_id: Optional[str]
    audience_type: str
    requested_quantity: int
    is_holdout: bool
    holdout_pct_bps: int
    allocation_rank: int
    allocated_quantity: int
    holdout_quantity: int
    mailable_quantity: int
    unit_cost_cents: int
    committed_cost_cents: int
    effective_response_bps: int
    gross_forecast_demand_cents: int
    forecast_demand_cents: int
    gross_margin_cents: int
    circulation_cost_cents: int
    contribution_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PagePlacement(TypedDict):
    id: str
    drop_id: str
    product_sku: str
    product_name: str
    unit_price_cents: int
    unit_cogs_cents: int
    demand_per_sq_inch_cents: int
    page_number: int
    sq_in_offset: int
    square_inches: int
    placement_position: str
    position_multiplier_bps: int
    forecast_space_demand_cents: int
    space_productivity_cents_per_sq_in: int
    created_at: str
    updated_at: str
    version: int


class SuppressionRule(TypedDict):
    id: str
    season_id: str
    rule_code: str
    channel_scope: str
    window_days: int
    max_contacts_per_window: int
    priority: int
    is_enabled: bool
    created_at: str
    updated_at: str
    version: int


class TestCell(TypedDict):
    id: str
    circulation_line_id: str
    cell_code: str
    test_type: str
    cell_role: str
    quantity: int
    responders: int
    demand_cents: int
    response_rate_bps: int
    lift_bps: int
    significance: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MatchbackRun(TypedDict):
    id: str
    drop_id: str
    attribution_variant: str
    attribution_window_days: int
    observed_drop_version: int
    matched_order_count: int
    attributed_order_count: int
    unmatched_order_count: int
    attributed_demand_cents: int
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Immutable audit rows: id + created_at only (no updated_at, no version)
# --------------------------------------------------------------------------
class PostalPresortBatch(TypedDict):
    id: str
    drop_id: str
    declared_tier: str
    piece_count: int
    effective_tier: str
    rate_cents_per_piece: int
    weight_surcharge_cents_per_piece: int
    batch_postage_cents: int
    is_automation_qualified: bool
    created_at: str


class ContactEvent(TypedDict):
    id: str
    housefile_segment_id: str
    drop_id: Optional[str]
    channel: str
    contact_date: str
    source: str
    channel_weight: int
    decay_factor_bps: int
    weighted_points: int
    created_at: str
