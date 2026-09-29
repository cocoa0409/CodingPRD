"""TypedDict shapes for every persisted entity of the PRD.

PRD 2.4 gives most rows `id`, `created_at`, `updated_at` and `version`.
`RecipeComponent` is the single exception: it carries only `id` and
`created_at`, so its shape below deliberately omits `updated_at` and
`version`.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Brand(CommonFields):
    legal_name: str
    doing_business_as: Optional[str]
    coverage_status: str
    coverage_reason: str
    counted_unit_count: int
    standard_item_count: int
    compliance_posture: str
    open_reprint_obligation_count: int
    overdue_board_count: int
    open_enforcement_escalated_count: int
    has_published_disclosure_packet: bool


class Jurisdiction(CommonFields):
    code: str
    name: str
    preemption_mode: str
    extra_requirement: str
    enforcement_tier: str
    sodium_warning_threshold_mg: int
    required_succinct_statement_variant: str
    reprint_grace_days: int
    assessed_penalty_cents_total: int


class Establishment(CommonFields):
    brand_id: str
    jurisdiction_id: str
    unit_label: str
    unit_status: str
    operates_under_brand_name: bool
    board_count: int
    outstanding_penalty_cents: int


class OfferWindow(TypedDict):
    start_date: str
    end_date: str


class MenuItem(CommonFields):
    brand_id: str
    name: str
    item_class: str
    variable_type: str
    first_offered_on: str
    labeling_exempt: bool
    labeling_status: str
    offer_windows: List[OfferWindow]
    cumulative_offered_days: int
    declared_calorie_min: Optional[int]
    declared_calorie_max: Optional[int]
    declared_sodium_mg: Optional[int]
    approved_recipe_version_no: Optional[int]
    allergen_groups: List[str]
    cross_contact_groups: List[str]


class Recipe(CommonFields):
    menu_item_id: str
    version_no: int
    status: str
    revision_round: int
    supersedes_recipe_id: Optional[str]
    change_note: str
    component_count: int
    computed_base_calories: float
    computed_declared_min: Optional[int]
    computed_declared_max: Optional[int]
    computed_sodium_mg: Optional[int]
    approved_at: Optional[str]


class RecipeComponent(TypedDict):
    """PRD 2.4: this row carries only `id` and `created_at`."""

    id: str
    created_at: str
    recipe_id: str
    component_name: str
    role: str
    grams: float
    calories_per_100g: float
    sodium_mg_per_100g: float
    added_sugar_g_per_100g: float
    allergen_group: str
    cross_contact_risk: str
    choice_group: Optional[str]
    selection_mode: Optional[str]
    selection_limit: Optional[int]
    component_calories: float
    component_sodium_mg: float


class NutritionAnalysis(CommonFields):
    recipe_id: str
    status: str
    method: str
    submitted_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    certified_at: Optional[str]
    declared_calorie_min: Optional[int]
    declared_calorie_max: Optional[int]
    declared_sodium_mg: Optional[int]


class AllergenRow(TypedDict):
    menu_item_id: str
    item_name: str
    allergen_groups: List[str]
    cross_contact_groups: List[str]


class DisclosurePacket(CommonFields):
    brand_id: str
    packet_version: int
    status: str
    cross_contact_statement: str
    cross_contact_statement_required: bool
    written_info_channels: List[str]
    allergen_rows: List[AllergenRow]
    covered_item_count: int
    allergen_matrix_complete: bool
    published_at: Optional[str]


class MenuBoard(CommonFields):
    establishment_id: str
    board_type: str
    succinct_statement_variant: str
    publication_status: str
    calorie_compliance_status: str
    effective_from: Optional[str]
    effective_to: Optional[str]
    reprint_deadline: Optional[str]
    reprint_count: int
    listing_count: int
    stale_listing_count: int


class MenuBoardListing(CommonFields):
    menu_board_id: str
    menu_item_id: str
    listing_status: str
    sodium_warning_icon: bool
    display_calorie_text: Optional[str]
    declared_min_snapshot: Optional[int]
    declared_max_snapshot: Optional[int]


class VarianceRequest(CommonFields):
    brand_id: str
    jurisdiction_id: str
    requirement_code: str
    status: str
    justification: str
    requested_start_date: str
    requested_end_date: str
    effective_start_date: Optional[str]
    effective_end_date: Optional[str]
    decision_note: Optional[str]
    decided_by_user_id: Optional[str]


class EnforcementAction(CommonFields):
    establishment_id: str
    jurisdiction_id: str
    citation_code: str
    status: str
    inspection_note: Optional[str]
    opened_at: str
    closed_at: Optional[str]
    info_round_count: int
    response_count: int
    last_response_type: Optional[str]
    penalty_basis: Optional[str]
    violation_unit_count: Optional[int]
    base_penalty_cents: Optional[int]
    admin_fee_cents: Optional[int]
    penalty_total_cents: int


# --- Computed read shapes (PRD 3.1) ---------------------------------------


class CoverageDetermination(TypedDict):
    brand_id: str
    basis: str
    counted_unit_count: int
    standard_item_count: int
    coverage_status: str
    coverage_reason: str
    persisted: bool


class ComplianceSummary(TypedDict):
    brand_id: str
    coverage_status: str
    coverage_reason: str
    counted_unit_count: int
    standard_item_count: int
    compliance_posture: str
    open_reprint_obligation_count: int
    overdue_board_count: int
    open_enforcement_escalated_count: int
    has_published_disclosure_packet: bool
    outstanding_penalty_cents_total: int


class EstablishmentBatchResult(TypedDict):
    brand_id: str
    created_count: int
    unit_status: str
    first_created_establishment_id: str
    brand_coverage_status: str
    brand_counted_unit_count: int


class ClockSetResult(TypedDict):
    current_utc: str
    boards_marked_overdue: int
    variances_expired: int


JsonDict = Dict[str, Any]
