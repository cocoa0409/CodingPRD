"""Response shapes for every resource the API exposes.

Thirteen of the fourteen collections carry the common system fields
``id``, ``created_at``, ``updated_at`` and ``version``.  ``Complaint`` is the
exception: it is append-only and carries only ``id`` and ``created_at`` beside
its own domain fields, so it deliberately does not inherit ``CommonFields``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class Envelope(TypedDict):
    """The uniform response envelope."""

    meta: Dict[str, Any]
    response_type: str
    data: Any


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class BrandProgram(CommonFields):
    brand_name: str
    retailer_name: str
    fiscal_year: int
    dev_budget_cents: int
    committed_budget_cents: int
    lifetime_committed_cents: int
    lifetime_released_cents: int
    active_item_count: int
    status: str


class BudgetLedger(TypedDict):
    """Computed read; carries no identity or version of its own."""

    program_id: str
    dev_budget_cents: int
    committed_budget_cents: int
    available_budget_cents: int
    lifetime_committed_cents: int
    lifetime_released_cents: int
    active_item_count: int


class CategoryGap(CommonFields):
    program_id: str
    category_code: str
    national_brand_name: str
    nb_retail_price_cents: int
    category_annual_sales_cents: int
    pl_share_pct: float
    unit_velocity_per_week: int
    shelf_slots_quota: int
    slots_consumed: int
    slots_consumed_lifetime: int
    slots_released_lifetime: int
    slots_open: int
    gap_score: Optional[float]
    recommended_tier: Optional[str]
    approved_tier: Optional[str]
    status: str


class Supplier(CommonFields):
    program_id: str
    legal_name: str
    plant_country: str
    gfsi_certificate_expiry: str
    qualification_status: str
    qualified_at: Optional[str]
    composite_score_cached: Optional[float]
    probation_item_count: int
    weighted_complaint_points: int


class SupplierScorecard(TypedDict):
    supplier_id: str
    rolling_12m_composite_score: float
    rolling_12m_audit_component: float
    rolling_12m_complaint_component: float
    rolling_12m_delivery_component: float
    rolling_12m_window_start: str
    period_to_date_composite_score: Optional[float]
    period_to_date_audit_component: Optional[float]
    period_to_date_complaint_component: Optional[float]
    period_to_date_delivery_component: Optional[float]
    period_to_date_window_start: Optional[str]


class PlantLine(CommonFields):
    supplier_id: str
    line_code: str
    daily_capacity_units: int
    changeover_buffer_minutes: int


class PlantAudit(CommonFields):
    supplier_id: str
    audit_type: str
    window_start: str
    window_end: str
    status: str
    result: Optional[str]
    food_safety_score: Optional[int]
    sanitation_score: Optional[int]
    traceability_score: Optional[int]
    capacity_score: Optional[int]
    audited_yield_pct: Optional[float]


class ProductItem(CommonFields):
    gap_id: str
    item_name: str
    tier: str
    pack_size_desc: str
    development_status: str
    quality_posture: str
    supplier_id: Optional[str]
    retail_price_cents: Optional[int]
    replacement_item_id: Optional[str]
    trailing_90d_units: int
    complaint_ppm_90d: float
    spec_revision_count: int


class CostModel(CommonFields):
    item_id: str
    supplier_id: str
    ingredient_cost_cents_per_unit: int
    packaging_cost_cents_per_unit: int
    conversion_cost_cents_per_unit: int
    effective_base_cents: int
    quoted_yield_pct: float
    freight_cents_per_pallet: int
    units_per_pallet: int
    moq_units: int
    tooling_cents: int
    landed_unit_cost_cents_as_quoted: int
    landed_unit_cost_cents_audited: Optional[int]
    status: str
    open_change_request_count: int


class ComparisonStudy(CommonFields):
    item_id: str
    study_type: str
    nb_control_lot_code: str
    status: str
    appearance_delta: Optional[float]
    aroma_delta: Optional[float]
    texture_delta: Optional[float]
    flavor_delta: Optional[float]
    parity_index: Optional[float]
    n_panelists: Optional[int]
    prefer_pl_count: Optional[int]
    prefer_nb_count: Optional[int]
    no_preference_count: Optional[int]
    preference_share_pct: Optional[float]
    verdict: Optional[str]


class ArtworkRound(CommonFields):
    item_id: str
    round_number: int
    status: str
    nutrition_status: str
    serving_size_g: float
    servings_per_container: float
    fat_g_per_100g: float
    satfat_g_per_100g: float
    carb_g_per_100g: float
    fiber_g_per_100g: float
    sugars_g_per_100g: float
    added_sugars_g_per_100g: float
    protein_g_per_100g: float
    sodium_mg_per_100g: float
    declared_calories: Optional[int]
    declared_fat_g: Optional[float]
    declared_satfat_g: Optional[float]
    declared_carb_g: Optional[float]
    declared_fiber_g: Optional[float]
    declared_sugars_g: Optional[float]
    declared_added_sugars_g: Optional[float]
    declared_protein_g: Optional[float]
    declared_sodium_mg: Optional[float]
    designer_user_id: str
    reviewer_user_id: Optional[str]


class LabelClaim(CommonFields):
    artwork_round_id: str
    claim_text: str
    claim_type: str
    substantiation_ref: Optional[str]
    depends_on_nutrition: bool
    status: str
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]


class Specification(CommonFields):
    item_id: str
    revision_no: int
    pinned_cost_model_id: str
    pinned_cost_model_version: int
    pinned_artwork_round_id: str
    pinned_artwork_version: int
    status: str
    slotting_fee_cents: Optional[int]
    locked_at: Optional[str]
    locked_by_user_id: Optional[str]


class ProductionRun(CommonFields):
    item_id: str
    specification_id: str
    plant_line_id: str
    run_type: str
    window_start: str
    window_end: str
    planned_units: int
    status: str
    committed_tooling_cents: int
    produced_units: Optional[int]
    completed_on_time: Optional[bool]
    completed_at: Optional[str]
    approved_by_user_id: Optional[str]
    hold_reason: Optional[str]


class Complaint(TypedDict):
    """Append-only: no ``updated_at`` and no ``version``."""

    id: str
    created_at: str
    item_id: str
    defect_category: str
    severity: str
    lot_code: str
    narrative: str
    received_at: str


class CostChangeRequest(CommonFields):
    item_id: str
    cost_model_id: str
    requested_ingredient_cost_cents_per_unit: int
    requested_packaging_cost_cents_per_unit: int
    requested_conversion_cost_cents_per_unit: int
    substitution_scope: str
    substitution_material_desc: Optional[str]
    raw_increase_cents: int
    increase_pct: float
    escalation_tier: str
    capped_increase_cents: int
    offset_fee_cents: int
    net_increase_cents: int
    counter_base_cents: Optional[int]
    round_number: int
    status: str
    decided_by_user_id: Optional[str]


Payload = Dict[str, Any]
Headers = Dict[str, str]
PaginatedData = List[Dict[str, Any]]
