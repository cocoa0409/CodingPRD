"""TypedDict shapes for every resource the PRD declares.

All fourteen resource types carry the common fields of PRD 2.4 -- `id`,
`created_at`, `updated_at` and `version` -- so those four are declared on a
shared base and inherited.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing_extensions is present on all supported hosts
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict


JsonDict = Dict[str, Any]


class CommonFields(TypedDict):
    """PRD 2.4: id, created_at, updated_at and version on every resource."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Facility(CommonFields, total=False):
    code: str
    name: str
    country_code: str
    housing_capacity: int
    bench_capacity: int
    approved_export_countries: List[str]
    approval_status: str
    suspension_reason: Optional[str]
    resident_sire_count: int


class Sire(CommonFields, total=False):
    registration_code: str
    name: str
    breed: str
    birth_date: str
    acquisition_cost_cents: int
    contract_price_cents: Optional[int]
    sire_id: Optional[str]
    dam_sire_id: Optional[str]
    pedigree_depth: int
    acquisition_status: str
    collection_status: str
    suspension_reason: Optional[str]
    housing_facility_id: Optional[str]
    isolation_days_applied: Optional[int]
    isolation_ends_at: Optional[str]
    published_production_index: float
    published_health_index: float
    published_composite_index: float
    published_evaluation_effective_at: Optional[str]
    progeny_daughter_count: int
    collection_count: int


class HealthTest(CommonFields, total=False):
    sire_id: str
    facility_id: str
    test_type: str
    sample_date: str
    validity_days: int
    result: str
    valid_until: Optional[str]
    resulted_at: Optional[str]
    recorded_by_user_id: Optional[str]
    retest_of_test_id: Optional[str]


class CollectionBooking(CommonFields, total=False):
    sire_id: str
    facility_id: str
    start_at: str
    end_at: str
    status: str
    cancel_reason: Optional[str]
    completed_at: Optional[str]
    collected_by_ref: Optional[str]


class Ejaculate(CommonFields, total=False):
    booking_id: str
    sire_id: str
    collected_at: str
    volume_ml: float
    concentration_m_per_ml: float
    motility_pct: float
    total_doses_theoretical: int
    qc_status: str
    post_thaw_motility_pct: Optional[float]
    morphology_normal_pct: Optional[float]
    evaluated_by_user_id: Optional[str]
    qc_decided_at: Optional[str]


class StrawLot(CommonFields, total=False):
    ejaculate_id: str
    sire_id: str
    product_line: str
    sexing_purity_pct: Optional[float]
    straw_count: int
    processing_cost_cents: int
    distribution_status: str
    doses_available: int
    doses_reserved: int
    doses_consigned: int
    doses_used: int
    doses_destroyed: int
    unit_book_value_cents: int
    valuation_basis: str
    pre_revaluation_unit_value_cents: Optional[int]
    released_by_user_id: Optional[str]
    rejected_reason: Optional[str]


class GenomicEvaluation(CommonFields, total=False):
    sire_id: str
    milk_kg: float
    fat_kg: float
    protein_kg: float
    somatic_cell_score: float
    fertility_pct: float
    longevity_months: float
    reliability_pct: float
    progeny_daughter_count: int
    effective_at: str
    status: str
    production_index: float
    health_index: float
    parent_average_index: float
    parent_average_weight: float
    composite_index: float
    evaluation_basis: str
    supersedes_evaluation_id: Optional[str]
    published_at: Optional[str]
    revaluation_delta_cents: int
    rollback_reason: Optional[str]


class CountryRequirement(CommonFields, total=False):
    country_code: str
    required_test_types: List[str]
    max_test_age_days: int
    min_isolation_days: int
    sexed_semen_allowed: bool
    embryo_allowed: bool


class ExportCertificate(CommonFields, total=False):
    sire_id: str
    straw_lot_id: str
    country_requirement_id: str
    destination_country_code: str
    status: str
    submission_round: int
    rejection_reason: Optional[str]
    issued_by_user_id: Optional[str]
    issued_at: Optional[str]
    expires_at: Optional[str]
    revoked_reason: Optional[str]


class Distributor(CommonFields, total=False):
    name: str
    country_code: str
    credit_limit_cents: int
    consignment_enabled: bool
    consignment_value_cents: int
    outstanding_balance_cents: int
    cumulative_doses_used: int


class Tank(CommonFields, total=False):
    distributor_id: str
    serial: str
    capacity_straws: int
    service_interval_days: int
    assigned_technician_name: Optional[str]
    technician_cert_expiry_at: Optional[str]
    last_service_at: str
    last_service_fill_pct: float
    ln2_level_pct: float
    next_service_due_at: str
    tank_status: str
    service_count: int
    straws_on_hand: int


class ConsignmentTransfer(CommonFields, total=False):
    straw_lot_id: str
    distributor_id: str
    tank_id: str
    export_certificate_id: Optional[str]
    doses: int
    unit_price_cents: int
    status: str
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    received_at: Optional[str]
    decided_at: Optional[str]
    doses_used: int
    doses_returned: int
    doses_on_hand: int
    carried_value_cents: int
    tank_service_count_at_dispatch: Optional[int]
    gross_cents: Optional[int]
    service_fee_cents: Optional[int]
    rebate_cents: Optional[int]
    settlement_total_cents: Optional[int]
    return_reason: Optional[str]


class CustomerHerd(CommonFields, total=False):
    herd_name: str
    distributor_id: str
    country_code: str
    target_product_line: str
    max_inbreeding_pct: float
    base_sire_id: Optional[str]
    recommendation_count: int


class MatingRecommendation(CommonFields, total=False):
    customer_herd_id: str
    dam_ref: str
    dam_sire_id: Optional[str]
    requested_product_line: str
    doses_requested: int
    excluded_sire_ids: List[str]
    recommended_sire_id: str
    straw_lot_id: str
    candidate_pool_size: int
    inbreeding_pct: float
    expected_conception_rate: float
    status: str
    doses_committed: int
    decided_at: Optional[str]


class InventoryValuation(TypedDict, total=False):
    plant_inventory_value_cents: int
    quarantine_value_cents: int
    released_value_cents: int
    lot_count: int


class ClockSweep(TypedDict, total=False):
    current_utc: str
    expired_health_test_ids: List[str]
    suspended_sire_ids: List[str]
    voided_booking_ids: List[str]
    service_due_tank_ids: List[str]
    out_of_service_tank_ids: List[str]
