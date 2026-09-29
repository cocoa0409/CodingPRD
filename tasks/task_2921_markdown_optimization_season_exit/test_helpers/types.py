"""TypedDict shapes for every resource this API returns.

Two resources are deliberately append-only and therefore carry only ``id``
and ``created_at``, with no ``updated_at`` and no ``version`` field at all:
a posted ``SalesWeek`` and a generated ``SeasonExitReview`` (PRD 2.4). Their
TypedDicts below omit both fields accordingly.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """The full set of common properties carried by most resources."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyFields(TypedDict):
    """The reduced set carried by append-only resources."""

    id: str
    created_at: str


class Season(CommonFields):
    code: str
    category: str
    season_start_date: str
    season_end_date: str
    exit_target_date: str
    exit_units_target: int
    sell_through_target_pct: float
    clearance_space_units: int
    reserved_clearance_units: int
    committed_clearance_units: int
    projected_exit_units: int
    status: str


class PriceZone(CommonFields):
    zone_code: str
    zone_type: str
    parent_zone_id: Optional[str]
    signage_lead_days: int
    region_code: Optional[str]


class Store(CommonFields):
    store_number: str
    price_zone_id: str
    region_code: Optional[str]
    clearance_bay_units: int
    committed_clearance_units: int
    available_clearance_units: int
    status: str


class Item(CommonFields):
    sku: str
    season_id: str
    category: str
    cluster_code: str
    vendor_code: str
    first_receipt_date: str
    protected_until_date: str
    original_retail_cents: int
    current_retail_cents: int
    unit_cost_cents: int
    units_received_total: int
    on_hand_units: int
    units_sold_total: int
    units_committed_disposition: int
    units_disposed_total: int
    sample_weeks: int
    sell_through_pct: float
    weeks_of_supply: float
    lifecycle_stage: str
    markdown_state: str
    permanent_markdown_reserve_cents: int
    promo_discount_cents: int


class SalesWeek(AppendOnlyFields):
    """Append-only: no ``updated_at`` and no ``version`` (PRD 2.4)."""

    item_id: str
    week_ending_date: str
    units_sold: int
    ticket_price_cents: int
    price_relative_pct: float


class ElasticityEstimate(CommonFields):
    item_id: str
    method: str
    resolved_method: str
    elasticity_coefficient: float
    sample_weeks_used: int
    peer_items_used: int
    confidence: str
    estimated_at: str
    certified_at: Optional[str]
    status: str


class MarkdownPlan(CommonFields):
    season_id: str
    item_id: str
    elasticity_estimate_id: str
    plan_type: str
    exit_date_target: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    revision_round: int
    recommended_depth_pct: float
    ladder_step_count: int
    gross_markdown_cents: int
    vendor_funded_cents: int
    net_markdown_cents: int
    projected_exit_units: int
    superseded_by_plan_id: Optional[str]
    status: str


class MarkdownStep(CommonFields):
    markdown_plan_id: str
    step_index: int
    effective_date: str
    depth_pct: float
    price_cents: int
    window_end_date_exclusive: Optional[str]
    status: str


class ZoneExecution(CommonFields):
    markdown_plan_id: str
    markdown_step_id: str
    price_zone_id: str
    store_id: Optional[str]
    execution_scope: str
    effective_date: str
    units_in_scope: int
    signage_due_date: str
    signage_status: str
    posted_at: Optional[str]
    posted_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    per_unit_markdown_cents: int
    line_markdown_cents: int
    price_cents_applied: int
    applied_at: Optional[str]
    status: str


class ClearanceReservation(CommonFields):
    season_id: str
    store_id: str
    markdown_plan_id: str
    reserved_units: int
    allocation_rank: int
    released_at: Optional[str]
    status: str


class VendorAllowanceAgreement(CommonFields):
    season_id: str
    vendor_code: str
    item_category_scope: str
    current_share_pct: float
    current_cap_cents: int
    agreed_share_pct: Optional[float]
    funding_cap_cents: Optional[int]
    remaining_cap_cents: Optional[int]
    recognized_total_cents: int
    round_index: int
    last_offer_by_role: str
    last_offer_by_user_id: str
    status: str


class VendorClaim(CommonFields):
    allowance_agreement_id: str
    markdown_plan_id: str
    claimed_cents: int
    recognized_cents: int
    recognized_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    status: str


class DispositionOrder(CommonFields):
    season_id: str
    item_id: str
    channel: str
    units: int
    unit_recovery_cents: int
    fmv_cents: Optional[int]
    projected_recovery_cents: int
    settled_units: int
    settled_recovery_cents: int
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str


class SeasonExitReview(AppendOnlyFields):
    """Append-only snapshot: no ``updated_at`` and no ``version`` (PRD 2.4)."""

    season_id: str
    review_type: str
    revenue_cents: int
    cogs_cents: int
    markdown_reserve_cents: int
    promo_discount_cents: int
    vendor_funding_cents: int
    disposition_recovery_cents: int
    gross_margin_cents: int
    sell_through_pct: float
    units_received_total: int
    units_sold_total: int
    units_disposed_total: int
    exit_units_variance: int
    sell_through_variance_pct: float
    generated_at: str
    generated_by_user_id: str


# Loose aliases used by helper signatures that accept any envelope payload.
JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
Headers = Dict[str, str]
