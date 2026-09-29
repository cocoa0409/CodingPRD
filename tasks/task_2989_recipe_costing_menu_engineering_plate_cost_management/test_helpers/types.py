"""Entity shapes and the closed vocabularies the PRD pins.

The enums are plain string containers so that a test can spell a status with a
symbol instead of a bare literal and a typo becomes an AttributeError rather
than a silently failing assertion.
"""

from typing import Any, Dict, List, Optional, TypedDict

# ─── Roles (PRD 2.1) ──────────────────────────────────


class Role:
    PLATFORM_ADMIN = "PlatformAdmin"
    RECIPE_DEVELOPER = "RecipeDeveloper"
    CULINARY_DIRECTOR = "CulinaryDirector"
    COST_ANALYST = "CostAnalyst"
    UNIT_MANAGER = "UnitManager"

    ALL = (
        PLATFORM_ADMIN,
        RECIPE_DEVELOPER,
        CULINARY_DIRECTOR,
        COST_ANALYST,
        UNIT_MANAGER,
    )


# ─── Closed vocabularies ──────────────────────────────


class BaseUom:
    GRAM = "GRAM"
    MILLILITER = "MILLILITER"
    EACH = "EACH"


class RegionCode:
    NE = "NE"
    SE = "SE"
    MW = "MW"
    WEST = "WEST"


class DistributorCode:
    BROADLINE = "BROADLINE"
    PRODUCE = "PRODUCE"
    PROTEIN = "PROTEIN"


class IngredientStatus:
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PriceFeedStatus:
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class IngredientPriceStatus:
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class RecipeType:
    SUB_RECIPE = "SUB_RECIPE"
    PLATED = "PLATED"


class RecipeStatus:
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CostState:
    STALE = "STALE"
    FRESH = "FRESH"


class CostBasis:
    LATEST_PUBLISHED = "LATEST_PUBLISHED"
    WEIGHTED_AVG_90D = "WEIGHTED_AVG_90D"


class ComponentType:
    INGREDIENT = "INGREDIENT"
    SUB_RECIPE = "SUB_RECIPE"


class ComponentStatus:
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class SyncState:
    CURRENT = "CURRENT"
    OUT_OF_DATE = "OUT_OF_DATE"


class MenuItemStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class MarginClass:
    UNCLASSIFIED = "UNCLASSIFIED"
    STAR = "STAR"
    PLOWHORSE = "PLOWHORSE"
    PUZZLE = "PUZZLE"
    DOG = "DOG"


class ProposalStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EFFECTIVE = "EFFECTIVE"


class ChangeType:
    COMPONENT_QTY = "COMPONENT_QTY"
    COMPONENT_ADD = "COMPONENT_ADD"
    COMPONENT_REMOVE = "COMPONENT_REMOVE"


class ApprovalStatus:
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


class PropagationStatus:
    NOT_STARTED = "NOT_STARTED"
    PREP_GUIDE_SYNCED = "PREP_GUIDE_SYNCED"
    COUNTS_SYNCED = "COUNTS_SYNCED"
    FULLY_PROPAGATED = "FULLY_PROPAGATED"


class PropagationTarget:
    PREP_GUIDE = "PREP_GUIDE"
    COUNT_SHEETS = "COUNT_SHEETS"


class ReviewBasis:
    SALES_MIX_BASED = "SALES_MIX_BASED"
    USAGE_BASED = "USAGE_BASED"


class ReviewStatus:
    OPEN = "OPEN"
    MIX_LOADED = "MIX_LOADED"
    CLASSIFIED = "CLASSIFIED"
    CLOSED = "CLOSED"


class VarianceFlag:
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    OVER_TOLERANCE = "OVER_TOLERANCE"
    NO_BASIS = "NO_BASIS"


class LtoStatus:
    PLANNED = "PLANNED"
    COSTED = "COSTED"
    LAUNCHED = "LAUNCHED"
    CLOSED = "CLOSED"
    RENEWED = "RENEWED"
    RETIRED = "RETIRED"


class LtoVerdict:
    PENDING = "PENDING"
    PROFITABLE = "PROFITABLE"
    UNPROFITABLE = "UNPROFITABLE"


class LtoDecision:
    RENEW = "RENEW"
    RETIRE = "RETIRE"


# ─── Entity shapes ────────────────────────────────────


class CommonProps(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Unit(CommonProps):
    code: str
    name: str
    region_code: str


class Ingredient(CommonProps):
    sku: str
    name: str
    base_uom: str
    pack_base_units: int
    trim_yield_bps: int
    cook_shrink_bps: int
    net_yield_bps: int
    allergen_mask: int
    kcal_per_base_unit_micros: int
    sodium_mcg_per_base_unit: int
    status: str
    retired_at: Optional[str]


class PriceFeed(CommonProps):
    distributor_code: str
    region_code: str
    feed_date: str
    status: str
    line_count: int
    published_at: Optional[str]
    superseded_price_count: int
    affected_recipe_count: int
    affected_menu_item_count: int


class IngredientPrice(CommonProps):
    price_feed_id: str
    ingredient_id: str
    region_code: str
    distributor_code: str
    pack_cost_micros: int
    pack_base_units_snapshot: int
    effective_from: str
    effective_to: Optional[str]
    status: str


class Recipe(CommonProps):
    code: str
    name: str
    recipe_type: str
    base_uom: str
    batch_yield_base_units: int
    portions_per_batch: int
    status: str
    cost_state: str
    cost_basis: Optional[str]
    last_rollup_at: Optional[str]
    batch_cost_micros: int
    portion_cost_micros: int
    allergen_mask: int
    kcal_per_portion_micros: int
    sodium_mcg_per_portion: int
    component_count: int
    depth: int
    open_spec_change_count: int


class RecipeComponent(CommonProps):
    recipe_id: str
    component_type: str
    ingredient_id: Optional[str]
    child_recipe_id: Optional[str]
    ep_quantity_base_units: int
    ap_quantity_base_units: int
    sequence_no: int
    status: str
    removed_at: Optional[str]
    unit_cost_micros_used: int
    pack_base_units_snapshot: int
    extended_cost_micros: int


class PrepGuide(CommonProps):
    recipe_id: str
    revision_no: int
    sync_state: str
    synced_spec_version: int
    component_count_snapshot: int
    batch_yield_base_units_snapshot: int
    portions_per_batch_snapshot: int


class MenuItem(CommonProps):
    code: str
    name: str
    recipe_id: str
    region_code: str
    current_price_cents: int
    target_food_cost_bps: int
    declared_allergen_mask: int
    is_kids_menu: bool
    status: str
    plate_cost_state: str
    cost_basis: Optional[str]
    plate_cost_micros: int
    plate_cost_cents: int
    food_cost_bps: int
    contribution_margin_cents: int
    margin_class: str
    allergen_mask: int
    sodium_mcg_per_portion: int
    is_lto: bool
    open_lto_count: int
    last_price_change_at: Optional[str]


class PriceChangeProposal(CommonProps):
    menu_item_id: str
    proposed_price_cents: int
    effective_from: str
    elasticity_bps: int
    status: str
    revision_round: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    last_revision_reason: Optional[str]
    price_delta_bps: Optional[int]
    projected_unit_delta_bps: Optional[int]
    baseline_units: Optional[int]
    projected_units: Optional[int]
    projected_food_cost_bps: Optional[int]
    market_cap_price_cents: Optional[int]
    effective_cap_price_cents: Optional[int]
    projected_contribution_delta_cents: Optional[int]


class SpecChangeOrder(CommonProps):
    recipe_id: str
    change_type: str
    target_component_id: Optional[str]
    new_ep_quantity_base_units: Optional[int]
    new_component_type: Optional[str]
    new_ingredient_id: Optional[str]
    new_child_recipe_id: Optional[str]
    approval_status: str
    propagation_status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_component_id: Optional[str]
    approved_at: Optional[str]
    pre_change_batch_cost_micros: Optional[int]
    pre_change_allergen_mask: Optional[int]
    pre_change_recipe_version: Optional[int]
    pre_change_ep_quantity_base_units: Optional[int]


class MenuPeriodReview(CommonProps):
    unit_id: str
    period_start: str
    period_end: str
    basis: str
    status: str
    total_units_sold: int
    total_gross_sales_cents: int
    popularity_threshold_bps: Optional[int]
    margin_threshold_cents: Optional[int]
    theoretical_food_cost_cents: Optional[int]
    actual_food_cost_cents: Optional[int]
    variance_bps: Optional[int]
    variance_flag: Optional[str]


class MenuMixLine(CommonProps):
    period_review_id: str
    menu_item_id: str
    units_sold: int
    gross_sales_cents: int
    plate_cost_cents_snapshot: int
    mix_pct_bps: Optional[int]
    cm_per_unit_cents: Optional[int]
    margin_class: str


class CountSheetLine(CommonProps):
    period_review_id: str
    ingredient_id: str
    opening_base_units: int
    received_base_units: int
    counted_base_units: int
    used_base_units: int
    expected_base_units: int
    variance_base_units: int
    valued_usage_micros: int
    sync_state: str
    synced_spec_version: Optional[int]


class LTOCampaign(CommonProps):
    menu_item_id: str
    region_code: str
    window_start: str
    window_end: str
    promo_price_cents: int
    forecast_units: int
    status: str
    promo_plate_cost_cents: int
    promo_food_cost_bps: int
    forecast_contribution_cents: int
    actual_units: Optional[int]
    actual_gross_sales_cents: Optional[int]
    promo_support_cost_cents: int
    promo_contribution_cents: int
    forecast_attainment_bps: int
    verdict: str


Payload = Dict[str, Any]
Headers = Dict[str, str]
Rows = List[Dict[str, Any]]
