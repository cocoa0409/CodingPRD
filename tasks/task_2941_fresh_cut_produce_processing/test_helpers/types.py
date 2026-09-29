"""Shapes of the resources the API returns.

These TypedDicts document the field inventory of every resource so that a test
reading a field has a single place to check its name and its type. They are
declared with ``total=False`` because a test normally asserts on a handful of
fields at a time, and because nullable fields are legitimately absent from
nothing - every declared key is always present in a response, but partial
dictionaries are convenient in fixtures.

Two conventions matter. Pound, percentage, chlorine and temperature figures are
JSON numbers, never strings, and every monetary figure is a whole number of
cents. And ``AntimicrobialReading`` is the one append-only resource: it carries
``id`` and ``created_at`` and deliberately has no ``updated_at`` and no
``version``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict, total=False):
    """The three system-managed audit fields every resource but one carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Product(CommonFields, total=False):
    code: str
    name: str
    commodity_class: str
    allergen_group: str
    min_dwell_seconds: int
    min_spin_rpm: int
    min_antimicrobial_ppm: float
    base_shelf_life_days: int
    min_yield_pct: float
    hold_and_release_required: bool
    active_spec_count: int


class CustomerSpec(CommonFields, total=False):
    product_id: str
    customer_code: str
    channel: str
    max_shelf_life_days_offered: int
    min_remaining_shelf_life_days_at_ship: int
    atmosphere_required: str
    case_net_weight_lb: float
    code_date_format: str
    spec_revision: int
    status: str
    superseded_at: Optional[str]


class Line(CommonFields, total=False):
    line_code: str
    required_disassembly_component_count: int
    max_atp_rlu: int
    posture: str
    open_corrective_action_count: int
    last_validated_sanitation_at: Optional[str]
    last_run_allergen_group: Optional[str]
    last_run_ended_at: Optional[str]


class WashSystem(CommonFields, total=False):
    system_code: str
    water_volume_gal: float
    max_concurrent_runs: int
    status: str
    last_changeout_at: str
    weighted_load_lb: float
    organic_load_index: float
    target_free_chlorine_ppm: Optional[float]
    changeout_count: int
    reading_sequence_high_water: int


class GrowerLot(CommonFields, total=False):
    grower_code: str
    ranch_block: str
    commodity_class: str
    harvest_datetime: str
    water_source: str
    adjacent_animal_operation: bool
    preharvest_test_result: str
    prior_rejected_receipt_count: int
    status: str
    preharvest_risk_score: Optional[int]
    trailing_risk_score: Optional[int]
    out_of_spec_receipt_count: int
    env_positive_run_count: int
    recalled_at: Optional[str]


class RawReceipt(CommonFields, total=False):
    grower_lot_id: str
    received_at: str
    pulp_temp_c: float
    gross_weight_lb: float
    tare_weight_lb: float
    net_weight_lb: float
    temp_grade: str
    shelf_life_deduction_days: int
    status: str
    trim_loss_lb: Optional[float]
    accepted_lb: Optional[float]
    remaining_lb: Optional[float]
    override_justification: Optional[str]
    dispositioned_by_user_id: Optional[str]


class AntimicrobialReading(TypedDict, total=False):
    """Append-only: only ``id`` and ``created_at``, no ``updated_at``, no ``version``."""

    id: str
    created_at: str
    wash_system_id: str
    reading_at: str
    free_chlorine_ppm: float
    ph: float
    orp_mv: int
    turbidity_ntu: float
    sequence_no: int
    taken_by_user_id: str
    organic_load_index_at_reading: float
    target_free_chlorine_ppm_at_reading: Optional[float]
    topup_ppm_required: Optional[float]
    below_target: bool


class SanitationEvent(CommonFields, total=False):
    line_id: str
    shift: str
    scheduled_for: str
    is_allergen_changeover: bool
    sequence_no: int
    status: str
    attempt_count: int
    started_at: Optional[str]
    performed_by_user_id: Optional[str]
    disassembled_component_count: int
    atp_rlu: Optional[int]
    allergen_swab_result: Optional[str]
    completed_at: Optional[str]
    validated_at: Optional[str]
    validated_by_user_id: Optional[str]
    failed_reason: Optional[str]


class EnvironmentalSwab(CommonFields, total=False):
    line_id: str
    zone: str
    site_code: str
    organism: str
    collected_at: str
    result: str
    resulted_at: Optional[str]
    resulted_by_user_id: Optional[str]


class CorrectiveAction(CommonFields, total=False):
    line_id: str
    source_type: str
    source_ref_id: str
    severity: str
    status: str
    reopen_count: int
    opened_at: str
    action_taken: Optional[str]
    implemented_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]


class ProcessRun(CommonFields, total=False):
    line_id: str
    product_id: str
    customer_spec_id: str
    wash_system_id: str
    rework_source_run_id: Optional[str]
    planned_start_at: str
    planned_end_at: str
    crew_size: int
    run_status: str
    disposition_status: str
    allergen_changeover_required: bool
    started_at: Optional[str]
    closed_at: Optional[str]
    target_ppm_at_start: Optional[float]
    required_dwell_seconds_at_start: Optional[int]
    actual_dwell_seconds: Optional[int]
    spin_rpm: Optional[int]
    spin_seconds: Optional[int]
    atmosphere_actual: Optional[str]
    water_gal_used: Optional[float]
    cases_produced: Optional[int]
    input_lb: float
    output_lb: Optional[float]
    yield_pct: Optional[float]
    min_ppm_observed: Optional[float]
    antimicrobial_excursion_count: Optional[int]
    provisional_shelf_life_days: Optional[int]
    provisional_code_date: Optional[str]
    final_shelf_life_days: Optional[int]
    final_code_date: Optional[str]
    total_run_cost_cents: Optional[int]
    per_case_cost_cents: Optional[int]
    cost_remainder_cents: Optional[int]
    cases_available: int
    cases_on_hold: int
    cases_shipped: int
    cases_destroyed: int


class LotConsumption(CommonFields, total=False):
    process_run_id: str
    raw_receipt_id: str
    consumed_lb: float
    status: str
    voided_at: Optional[str]
    recorded_by_user_id: str


class FinishedCase(CommonFields, total=False):
    process_run_id: str
    case_sequence: int
    case_code: str
    net_weight_lb: float
    code_date: str
    code_date_label: str
    allocated_cost_cents: int
    status: str
    shipped_at: Optional[str]


class HoldRecord(CommonFields, total=False):
    process_run_id: str
    reason: str
    status: str
    test_round: int
    opened_at: str
    closed_at: Optional[str]
    latest_test_type: Optional[str]
    latest_test_result: Optional[str]
    latest_apc_cfu_g: Optional[int]
    resulted_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    cases_held_count: int
    shipped_case_count: int


class Traceability(TypedDict, total=False):
    """The consolidated one-hop recall view of a run, derived on every read."""

    process_run_id: str
    product_code: str
    customer_code: str
    grower_lot_ids: List[str]
    grower_codes: List[str]
    raw_receipt_ids: List[str]
    active_consumption_count: int
    voided_consumption_count: int
    case_count: int
    shipped_case_count: int
    on_hold_case_count: int
    destroyed_case_count: int
    effective_code_date: Optional[str]
    rework_source_run_id: Optional[str]
    rework_ancestor_run_ids: List[str]


# A response payload of any shape, for helpers that do not care which resource.
Payload = Dict[str, Any]
