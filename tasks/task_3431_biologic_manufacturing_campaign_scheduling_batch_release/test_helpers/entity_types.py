"""Entity TypedDicts.

Every primary resource carries id/created_at/updated_at/version (PRD §2.5),
except TemperatureReading, which is immutable and carries only id/created_at.
"""
from typing import Dict, List, Optional, TypedDict


class ManufacturingSite(TypedDict):
    id: str
    name: str
    region: str
    monthly_capacity_hours: int
    cold_storage_capacity_units: int
    licensed_authorities: List[str]
    release_posture: str
    open_critical_deviation_count: int
    open_critical_finding_count: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    product_code: str
    molecule_type: str
    market_scope: str
    requires_cold_chain: bool
    min_storage_temp_c: float
    max_storage_temp_c: float
    shelf_life_hours: int
    changeover_hours: int
    same_product_turnaround_hours: int
    required_materials: List[Dict]
    created_at: str
    updated_at: str
    version: int


class BioreactorTrain(TypedDict):
    id: str
    site_id: str
    train_code: str
    capacity_liters: int
    supported_molecule_types: List[str]
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    train_id: str
    product_id: str
    demand_type: str
    planned_start_utc: str
    planned_end_utc: str
    upstream_hours: int
    downstream_hours: int
    allocated_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeedTrainStage(TypedDict):
    id: str
    campaign_id: str
    stage_index: int
    planned_duration_hours: int
    started_at: Optional[str]
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BatchLot(TypedDict):
    id: str
    campaign_id: str
    lot_number: str
    product_id: str
    process_status: str
    quality_status: str
    quality_hold_return_status: Optional[str]
    manufactured_by_user_id: str
    quantity_units: int
    provisional_yield_units: int
    final_yield_units: Optional[int]
    available_to_ship_units: int
    process_completed_at: Optional[str]
    expiry_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InProcessTest(TypedDict):
    id: str
    batch_lot_id: str
    test_type: str
    phase: str
    measured_value: float
    unit: str
    spec_min: float
    spec_max: float
    is_in_spec: bool
    supersedes_test_id: Optional[str]
    status: str
    recorded_by_user_id: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deviation(TypedDict):
    id: str
    batch_lot_id: str
    kind: str
    severity: str
    description: str
    linked_test_id: Optional[str]
    status: str
    conclusion: Optional[str]
    capa_summary: Optional[str]
    opened_by_user_id: str
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    batch_lot_id: str
    destination_region: str
    market_type: str
    quantity_units: int
    status: str
    shipped_at: Optional[str]
    delivered_at: Optional[str]
    excursion_evaluation: str
    evaluation_variant: str
    created_at: str
    updated_at: str
    version: int


class TemperatureReading(TypedDict):
    # Immutable log entry: carries ONLY id + created_at (PRD §2.5) —
    # no updated_at, no version.
    id: str
    shipment_id: str
    recorded_at: str
    temperature_c: float
    created_at: str


class ComparabilityStudy(TypedDict):
    id: str
    product_id: str
    change_type: str
    baseline_attribute_values: List[float]
    candidate_batch_ids: List[str]
    status: str
    authority: Optional[str]
    baseline_mean: Optional[float]
    equivalence_margin: Optional[float]
    created_at: str
    updated_at: str
    version: int


class RegulatoryInspection(TypedDict):
    id: str
    site_id: str
    authority: str
    status: str
    findings: List[Dict]
    open_critical_finding_count: int
    response_summary: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialLot(TypedDict):
    id: str
    site_id: str
    material_name: str
    is_single_source: bool
    quantity_available: float
    status: str
    created_at: str
    updated_at: str
    version: int
