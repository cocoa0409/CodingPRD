"""
Typed shapes for the resources the API returns.

Field names and nullability follow the PRD exactly. Every record carries the
common properties of PRD 2.7 — a UUID `id`, a `created_at`, an `updated_at` and
a `version` — with the single documented exception of a discharge sample, which
carries only `id` and `created_at` because it is immutable once written.
"""

from typing import Optional, TypedDict


class CommonFields(TypedDict):
    """The common record properties every record but a discharge sample carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Hatchery(CommonFields, total=False):
    name: str
    station_code: str
    water_source_type: str
    annual_water_right_af: float
    rearing_capacity_lbs: float
    oxygen_supply_lpm: float
    effluent_permit_number: str
    tss_permit_limit_mg_l: float
    annual_budget_cents: int
    water_reserved_af: float
    water_used_af: float
    water_available_af: float
    budget_committed_cents: int
    budget_spent_cents: int
    budget_available_cents: int
    biomass_on_hand_lbs: float
    density_index: float
    exceedance_count_rolling: int
    operating_posture: str


class EffluentReading(TypedDict, total=False):
    """A discharge sample: the one record type with neither version nor updated_at."""

    id: str
    created_at: str
    hatchery_id: str
    sampled_at: str
    tss_mg_l: float
    total_phosphorus_mg_l: float
    flow_af: float
    status: str
    exceedance_margin_mg_l: float


class BroodStock(CommonFields, total=False):
    hatchery_id: str
    species: str
    strain: str
    female_count: int
    male_count: int
    expected_fecundity_per_female: int
    spawning_window_start: str
    spawning_window_end: str
    egg_take_target: int
    status: str
    females_reserved: int
    females_spent: int
    females_available: int
    cumulative_eggs_taken: int


class SpawnEvent(CommonFields, total=False):
    brood_stock_id: str
    planned_take_date: str
    females_spawned: int
    target_release_count: int
    status: str
    planned_eggs: int
    cumulative_survival: float
    required_eggs_for_target: int
    projected_release_count: int
    water_reserved_af: float
    eggs_taken: Optional[int]
    taken_at: Optional[str]


class RearingLot(CommonFields, total=False):
    hatchery_id: str
    spawn_event_id: str
    species: str
    rearing_stage: str
    health_status: str
    certificate_expires_at: Optional[str]
    initial_count: int
    count_on_hand: int
    reserved_count: int
    cumulative_mortality_count: int
    avg_weight_g: float
    initial_biomass_lbs: float
    biomass_lbs: float
    cumulative_mortality_biomass_lbs: float
    cumulative_feed_lbs: float
    growth_rate_g_per_day: Optional[float]
    fcr_biological: Optional[float]
    fcr_economic: Optional[float]


class HealthInspection(CommonFields, total=False):
    lot_id: str
    inspection_type: str
    sample_size: int
    sampled_at: str
    status: str
    result: Optional[str]
    pathogen_code: Optional[str]
    retest_count: int
    sampled_by_user_id: str
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    certificate_expires_at: Optional[str]
    treatment_code: Optional[str]
    withdrawal_days: Optional[int]
    treatment_completed_at: Optional[str]
    withdrawal_clears_at: Optional[str]
    escalated_from_retests: bool


class Water(CommonFields, total=False):
    name: str
    county: str
    water_class: str
    habitat_suitability_score: float
    angler_demand_index: float
    plan_species: str
    plan_target_count: int
    access_type: str
    status: str
    allocated_count_ytd: int
    released_count_ytd: int
    last_release_at: Optional[str]
    plan_shortfall_count: int
    plan_fill_pct: float


class StockingRequest(CommonFields, total=False):
    water_id: str
    species: str
    requested_count: int
    size_class: str
    justification: str
    requester_kind: str
    requested_by_user_id: str
    status: str
    priority_score: float
    allocated_count: int
    allocation_plan_id: Optional[str]
    deferral_reason: Optional[str]
    allocated_at: Optional[str]
    fulfilled_at: Optional[str]


class AllocationPlan(CommonFields, total=False):
    hatchery_id: str
    fiscal_year: int
    species: str
    size_class: str
    available_count: int
    public_request_cap_pct: float
    allocation_mode: str
    status: str
    allocated_total_count: int
    unmet_demand_count: int
    public_allocated_count: int
    run_count: int


class TransportUnit(CommonFields, total=False):
    hatchery_id: str
    unit_code: str
    tank_gallons: float
    max_load_lbs: float
    oxygen_lpm: float
    certification_expires_at: str
    status: str
    current_event_id: Optional[str]


class StockingEvent(CommonFields, total=False):
    stocking_request_id: str
    lot_id: str
    transport_unit_id: str
    fish_count: int
    scheduled_depart_at: str
    scheduled_return_at: str
    mark_type: str
    marked_count: int
    status: str
    planned_load_lbs: float
    transport_cost_cents: int
    oxygen_flow_lpm: float
    max_fish_allowed: Optional[int]
    effective_marked_count: int
    loaded_at: Optional[str]
    load_water_temp_c: Optional[float]
    measured_load_lbs: Optional[float]
    arrived_at: Optional[str]
    site_water_temp_c: Optional[float]
    tempering_minutes: Optional[int]
    tempering_minutes_required: Optional[int]
    released_at: Optional[str]
    released_count: Optional[int]
    aborted_at: Optional[str]
    abort_reason: Optional[str]
    recovered_count: Optional[int]
    creel_sample_fraction: Optional[float]
    contribution_index_cohort: Optional[float]
    contribution_index_harvest: Optional[float]
